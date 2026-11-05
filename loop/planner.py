"""Bayesian planner for the rig loop: proposes the next flow setpoints from per-setpoint results.

Same model as lab_loop.BayesAgent (bayes_misclass, the arm that reached the full-scan boundary with the
least protein in simulation): a GP on the phase-separated fraction of each setpoint, and candidates ranked
by the probability that the GP has them on the wrong side of 0.5. Here the space is the rig's own:
flows of the scanned pumps (G3BP1, PolyA RNA, PEG on Beta3 2026-10-28), buffer making up a fixed total.
"""
import itertools

import numpy as np
from scipy.stats import norm
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel


class Space:
    """Reachable flow settings. pumps: {pump index: name} for the scanned pumps; buffer fills the rest."""

    def __init__(self, pumps, buffer_pump, total=120.0, fmin=2.5, step=0.05):
        self.pumps, self.buffer_pump, self.total, self.fmin = dict(pumps), buffer_pump, total, fmin
        levels = np.arange(0, 1 + 1e-9, step)
        lo = fmin / total
        grid = [x for x in itertools.product(levels, repeat=len(pumps))
                if sum(x) <= 1 - lo + 1e-9 and min(x) >= lo - 1e-9]
        self.G = np.array(grid)  # flow fractions of the scanned pumps

    def flows(self, x):
        """Flow fractions -> {pump index: uL/h} for every aqueous pump, buffer included."""
        f = {p: round(float(v) * self.total, 2) for p, v in zip(self.pumps, x)}
        f[self.buffer_pump] = round(self.total - sum(f.values()), 2)
        return f

    def x(self, flows):
        return np.array([float(flows[p]) / self.total for p in self.pumps])


def fit_gp(x, frac, n):
    frac = np.clip(np.asarray(frac, float), 0, 1)
    var = (frac * (1 - frac) + 0.05) / np.maximum(np.asarray(n, float), 1)
    k = ConstantKernel(0.25, (1e-2, 4)) * Matern(0.15, (0.03, 1.0), nu=2.5) + WhiteKernel(1e-3, (1e-6, 1e-1))
    return GaussianProcessRegressor(k, alpha=var, normalize_y=True, random_state=0).fit(np.asarray(x), frac)


class Planner:
    """propose(results, pending, k) -> k candidates, best first.

    results: [{'x': fractions, 'frac': PS fraction, 'n': droplets}] for setpoints with data back;
    pending: fractions of setpoints sent but not yet measured (kept apart so a batch spreads out)."""

    def __init__(self, space, warm=6, seed=0, spacing=2, allowed=None):
        self.s, self.warm, self.spacing = space, warm, spacing
        self.rng = np.random.default_rng(seed)
        self.allowed = None if allowed is None else np.asarray(allowed, bool)  # mask over space.G, or None

    def propose(self, results, pending, k=5):
        G = self.s.G
        taken = [np.asarray(p) for p in pending]
        if len(results) < self.warm:
            # warm-up: spread-out random settings until the GP has something to fit
            order = self.rng.permutation(len(G))
            mu, sd, acq = np.full(len(G), np.nan), np.full(len(G), np.nan), np.zeros(len(G))
        else:
            gp = fit_gp([r['x'] for r in results], [r['frac'] for r in results], [r['n'] for r in results])
            mu, sd = gp.predict(G, return_std=True)
            sd = np.maximum(sd, 1e-6)
            acq = norm.cdf(-np.abs(mu - 0.5) / sd)  # probability the map has this point on the wrong side
            order = np.argsort(-acq)
        step = np.diff(np.unique(G[:, 0]))[:1].item() if len(G) > 1 else 0.05
        picks = []
        for j in order:
            if self.allowed is not None and not self.allowed[j]:
                continue
            if all(np.linalg.norm(G[j] - q) > self.spacing * step for q in taken + [G[i] for i in picks]):
                picks.append(j)
            if len(picks) == k:
                break
        return [dict(x=G[j].tolist(), flows=self.s.flows(G[j]), mu=None if np.isnan(mu[j]) else float(mu[j]),
                     sd=None if np.isnan(sd[j]) else float(sd[j]), acq=float(acq[j]),
                     mode='warm-up' if len(results) < self.warm else 'bayes_misclass')
                for j in picks]


def phase_map(space, results):
    """The GP's current phase map over the whole reachable grid: P(PS) mean and sd per grid point.

    results: [{'x': fractions, 'frac': PS fraction, 'n': droplets}] (needs >= 2). None if too few."""
    if len(results) < 2:
        return None
    gp = fit_gp([r['x'] for r in results], [r['frac'] for r in results], [r['n'] for r in results])
    mu, sd = gp.predict(space.G, return_std=True)
    return dict(names=list(space.pumps.values()), grid=space.G.round(4).tolist(),
                mu=np.clip(mu, 0, 1).round(4).tolist(), sd=sd.round(4).tolist(), n_results=len(results))
