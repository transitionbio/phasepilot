"""Animate the planner's GP phase maps from a run (log/maps/map_<n>.json + results.csv) as a smooth video:
each map crossfades into the next (heatmap, boundary and points), so the boundary is seen moving through
phase space instead of jumping at each decision.  Styled like the PhasePilot tab's map.

    python render_map_anim.py --run runs/<stamp> --out map_anim.mp4 [--hold 1.2 --fade 1.8]
"""
import argparse
import csv
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

FF = Path.home() / 'phasescan-closed-loop/.venv-gui/lib/python3.7/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux64-v4.2.2'
FPS = 30


def load_map(path, z):
    m = json.loads(Path(path).read_text())
    g = np.asarray(m['grid']); mu = np.asarray(m['mu']); sd = np.asarray(m['sd'])
    keep = np.isclose(g[:, 2], z)
    g, mu, sd = g[keep], mu[keep], sd[keep]
    xs, ys = np.unique(g[:, 0]), np.unique(g[:, 1])
    P = np.full((len(ys), len(xs)), np.nan); S = np.full((len(ys), len(xs)), np.nan)
    P[np.searchsorted(ys, g[:, 1]), np.searchsorted(xs, g[:, 0])] = mu
    S[np.searchsorted(ys, g[:, 1]), np.searchsorted(xs, g[:, 0])] = sd
    return m['decision'], m['n_results'], xs, ys, P, S


def rgba(P, S):
    ok = ~np.isnan(P)
    out = np.zeros(P.shape + (4,))
    p = np.nan_to_num(P); s = np.nan_to_num(S)
    out[..., 0] = p; out[..., 1] = 60 / 255; out[..., 2] = 1 - p
    out[..., 3] = np.where(ok, 0.8 * np.clip(1 - 2 * s, 0.15, 1), 0)
    return out


def main():
    a = argparse.ArgumentParser()
    a.add_argument('--run', required=True); a.add_argument('--out', required=True)
    a.add_argument('--hold', type=float, default=1.2); a.add_argument('--fade', type=float, default=1.8)
    a.add_argument('--size', default='1180x700')
    args = a.parse_args()
    run = Path(args.run)
    rows = list(csv.DictReader(open(run / 'log/results.csv')))
    # fixed slice: the third-pump level nearest the median of all measured setpoints
    xs_all = [json.loads(r['x']) for r in rows if r['x']]
    first = json.loads(sorted(run.glob('log/maps/map_*.json'))[0].read_text())
    levels = np.unique(np.asarray(first['grid'])[:, 2])
    z = levels[np.argmin(np.abs(levels - np.median([x[2] for x in xs_all])))]
    names = first['names']
    maps = [load_map(p, z) for p in sorted(run.glob('log/maps/map_*.json'))]

    def points_at(decision):
        pts = {}
        for r in rows:
            if int(r['decision']) <= decision and r['x']:
                pts[r['id']] = (json.loads(r['x']), float(r['frac']) if r['frac'] else None, r['in_flight'] == 'True')
        return pts

    w, h = (int(v) for v in args.size.split('x'))
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100, facecolor='black')
    ax = fig.add_axes([0.08, 0.1, 0.9, 0.8], facecolor='black')
    xs, ys = maps[0][2], maps[0][3]
    dx, dy = float(np.diff(xs).min()), float(np.diff(ys).min())
    ok_any = ~np.isnan(maps[-1][4])
    okx, oky = np.where(ok_any.any(axis=0))[0], np.where(ok_any.any(axis=1))[0]
    extent = [xs[0] - dx / 2, xs[-1] + dx / 2, ys[0] - dy / 2, ys[-1] + dy / 2]
    work = Path(tempfile.mkdtemp())
    n = 0

    def draw(P, S, title, pts, alpha_pts):
        nonlocal n
        ax.clear(); ax.set_facecolor('black')
        ax.imshow(rgba(P, S), origin='lower', extent=extent, interpolation='nearest', aspect='auto')
        try:
            ax.contour(xs, ys, np.where(np.isnan(P), 0, P), levels=[0.5], colors='white', linestyles='--', linewidths=2)
        except Exception:
            pass
        for sid, (x, frac, flight) in pts.items():
            col = (frac, 60 / 255, 1 - frac) if frac is not None else 'none'
            ax.scatter([x[0]], [x[1]], s=140, c=[col] if frac is not None else 'none', edgecolors='white' if flight else 'black',
                       linewidths=2, zorder=5, alpha=alpha_pts.get(sid, 1))
            ax.annotate(sid, (x[0], x[1]), xytext=(6, 6), textcoords='offset points', color='white', fontsize=13,
                        alpha=alpha_pts.get(sid, 1))
        ax.set_xlim(xs[okx[0]] - dx, xs[okx[-1]] + dx); ax.set_ylim(ys[oky[0]] - dy, ys[oky[-1]] + 1.5 * dy)
        ax.set_xlabel(f'{names[0]} (flow fraction)', color='white', fontsize=14)
        ax.set_ylabel(f'{names[1]} (flow fraction)', color='white', fontsize=14)
        ax.tick_params(colors='white', labelsize=12)
        for s in ax.spines.values():
            s.set_color('#888888')
        ax.set_title(title, color='white', fontsize=16, loc='left')
        fig.savefig(work / f'f_{n:05d}.png', dpi=100, facecolor='black')
        n += 1

    hold, fade = int(args.hold * FPS), int(args.fade * FPS)
    for i, (dec, nres, _, _, P, S) in enumerate(maps):
        pts = points_at(dec)
        title = f'GP phase map after decision {dec} ({nres} results), {names[2]} = {z:.2f} slice'
        for _ in range(hold):
            draw(P, S, title, pts, {})
        if i + 1 < len(maps):
            dec2, nres2, _, _, P2, S2 = maps[i + 1]
            pts2 = points_at(dec2)
            new = {k for k in pts2 if k not in pts or pts2[k][1] != pts[k][1]}
            for k in range(1, fade + 1):
                t = k / fade
                Pi = np.where(np.isnan(P) & np.isnan(P2), np.nan, np.nan_to_num(P) * (1 - t) + np.nan_to_num(P2) * t)
                Si = np.nan_to_num(S) * (1 - t) + np.nan_to_num(S2) * t
                merged = dict(pts); merged.update({k_: pts2[k_] for k_ in new})
                draw(Pi, Si, title if t < 0.5 else f'GP phase map after decision {dec2} ({nres2} results), {names[2]} = {z:.2f} slice',
                     merged, {k_: t for k_ in new})
    for _ in range(hold):
        draw(maps[-1][4], maps[-1][5], f'GP phase map after decision {maps[-1][0]} ({maps[-1][1]} results), {names[2]} = {z:.2f} slice',
             points_at(maps[-1][0]), {})
    subprocess.run([str(FF), '-y', '-loglevel', 'error', '-framerate', str(FPS), '-i', str(work / 'f_%05d.png'),
                    '-vf', 'format=yuv420p', '-c:v', 'libx264', '-preset', 'fast', args.out], check=True)
    print('wrote', args.out, n, 'frames', n / FPS, 's; slice', names[2], z)


if __name__ == '__main__':
    main()
