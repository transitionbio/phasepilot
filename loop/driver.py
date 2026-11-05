"""PhasePilot rig loop: live droplet results -> Bayesian planner -> Muse -> setpoint queue -> GUI -> pumps.

Reads
  <worker out>/part_*.parquet   live worker droplets (frame time, CNN phase_separated_prob, SAM QC columns)
  <queue>/events.csv            when each setpoint was accepted / done (written by the GUI's queue_flowscan)
Writes
  <queue>/pending/*.json        the next setpoint (via setpoint_queue.SetpointQueue)
  <log>/decisions.jsonl         one record per decision: evidence, planner candidates, Muse's prompt and reply,
                                who decided (muse / planner fallback / controller), the action, the queued id
  <log>/results.csv             per-setpoint result table as the loop saw it at each decision
  <log>/map.json, maps/         the planner GP's phase map (P(PS) mean, sd over the grid) after each decision

Droplets made while setpoint S is held reach the imaging position `lag_s` later, so S's result is the droplets
imaged in [accepted + settle_s + lag_s, done + lag_s]. Until then S is "in flight" and the planner keeps new
proposals away from it. Droplets SAM flags (sam_ok == 0: cut by the frame edge, or not a droplet) are left out.

Setpoints run back to back: whenever fewer than `depth` are queued or holding, the loop decides the next one,
so pumps never idle while results incubate (the pipelined mode of lab_loop.py).

    python driver.py --worker-out <rig>/live/out --queue <rig>/queue --log <rig>/loop_log \
        --lag 180 --hold 60 --budget 30 --reserve 5
"""
import argparse
import glob
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from muse import MuseClient, brief
from planner import Planner, Space, phase_map
from setpoint_queue import SetpointQueue

# Beta3, 2026-10-28 G3BP1/PolyA/PEG config: pump index -> reagent
PUMPS = {3: 'G3BP1', 2: 'PolyA', 1: 'PEG'}
BUFFER = 4
PROTEIN_PUMP = 3
QUESTION = ('Where do G3BP1 / PolyA RNA / PEG droplets phase separate? Locate the boundary using as little '
            'G3BP1 as possible.')


class Loop:

    def __init__(self, a, queue=None, muse=None, now=time.time):
        self.a, self.now = a, now
        self.space = Space(PUMPS, BUFFER, total=a.total, fmin=a.fmin, step=a.step)
        self.planner = Planner(self.space, warm=a.warm, seed=a.seed)
        self.queue = queue or SetpointQueue(a.queue)
        self.muse = muse or MuseClient()
        self.log = Path(a.log)
        self.log.mkdir(parents=True, exist_ok=True)
        # what the PhasePilot tab needs to find everything for this run
        previous = json.loads((self.log / 'run.json').read_text()) if (self.log / 'run.json').exists() else {}
        self.started = previous.get('started', self.now())
        (self.log / 'run.json').write_text(json.dumps(dict(
            started=self.started, worker_out=str(a.worker_out), queue=str(a.queue), budget_ul=a.budget,
            reserve_ul=a.reserve, hold_s=a.hold, lag_s=a.lag, pumps={str(k): v for k, v in PUMPS.items()},
            buffer_pump=BUFFER, protein_pump=PROTEIN_PUMP, question=a.question,
            muse_model=getattr(self.muse, 'model', None), muse_endpoint=getattr(self.muse, 'base_url', None),
            muse_key=bool(getattr(self.muse, 'api_key', None)), sam='SAM ViT-B (sam_vit_b_01ec64)'), indent=1))
        self.parts = {}
        self.traces = {}  # trace_*.parquet: one row per frame, n_droplets 0 when nothing was detected
        self.sent = {}   # id -> flows, for every setpoint this loop queued
        self.n = 0
        self.paused = False
        # resuming a paused run in the same log folder: carry on the decision count and setpoint ids
        if (self.log / 'decisions.jsonl').exists():
            for rec in (json.loads(line) for line in (self.log / 'decisions.jsonl').read_text().splitlines() if line):
                self.n = max(self.n, rec['decision'])
                if rec.get('setpoint'):
                    self.sent[rec['setpoint']] = {int(k): v for k, v in rec['flows'].items()}

    # ------------------------------------------------------------------ evidence
    def droplets(self):
        for f in glob.glob(os.path.join(self.a.worker_out, 'part_*.parquet')):
            if f not in self.parts:
                self.parts[f] = pd.read_parquet(f)
        if not self.parts:
            return pd.DataFrame(columns=['time', 'phase_separated_prob', 'sam_ok', 'radius'])
        return pd.concat(self.parts.values(), ignore_index=True)

    def frames(self, drops):
        """One row per imaged frame (time, n_droplets). From the worker's trace files when it writes them
        (empty frames count as 0 droplets), otherwise from the droplets themselves."""
        for f in glob.glob(os.path.join(self.a.worker_out, 'trace_*.parquet')):
            if f not in self.traces:
                t = pd.read_parquet(f)
                self.traces[f] = pd.DataFrame({'time': t['time'], 'n_droplets': t['n_droplets'].fillna(0)})
        if self.traces:
            return pd.concat(self.traces.values(), ignore_index=True).dropna(subset=['time'])
        if not len(drops):
            return pd.DataFrame(columns=['time', 'n_droplets'])
        return drops.groupby('time').size().rename('n_droplets').reset_index()

    def setpoints(self, ev):
        """One row per accepted setpoint: id, flows, start, end (None while holding)."""
        rows = []
        acc = ev[ev.event == 'accepted']
        for _, r in acc.iterrows():
            later = ev[(ev.id.astype(str) == str(r.id)) & ev.event.isin(['done', 'cancelled']) & (ev.time >= r.time)]
            flows = {p: float(r[str(p)]) for p in list(PUMPS) + [BUFFER] if str(p) in r and pd.notna(r[str(p)])}
            rows.append(dict(id=str(r.id), flows=flows, start=float(r.time),
                             end=float(later.time.iloc[0]) if len(later) else None))
        return rows

    def results(self, ev, drops):
        out = []
        t = self.now()
        for s in self.setpoints(ev):
            x = self.space.x(s['flows']) if all(p in s['flows'] for p in PUMPS) else None
            row = dict(id=s['id'], x=None if x is None else x.tolist(), flows=s['flows'], start=s['start'],
                       end=s['end'], frac=None, n=0, qc='')
            lo = s['start'] + self.a.settle + self.a.lag
            hi = (s['end'] if s['end'] is not None else t) + self.a.lag
            row['in_flight'] = s['end'] is None or t < hi
            d = drops[(drops.time >= lo) & (drops.time <= hi)]
            if 'sam_ok' in d:
                bad = int((d.sam_ok == 0).sum())
                checked = int(d.sam_ok.notna().sum())
                d = d[d.sam_ok != 0]
                if checked:
                    row['qc'] = f'SAM {bad}/{checked} rejected'
            for ch in ('488', '546', '647'):  # dye barcodes: what actually reached the droplets
                row[f'I{ch}'] = float(d[ch].median()) if ch in d and len(d) else None
            cls = d.phase_separated_prob.dropna()
            row['n'] = int(len(cls))
            if len(cls) >= self.a.min_droplets:
                row['frac'] = float((cls > 0.5).mean())
            elif not row['in_flight']:
                row['qc'] = (row['qc'] + '; ' if row['qc'] else '') + f'only {len(cls)} droplets'
            out.append(row)
        return out

    def image_qc(self, drops):
        t = self.now()
        recent = drops[drops.time >= t - 300]
        if not len(recent):
            return 'no droplets imaged in the last 5 min'
        per_frame = recent.groupby('time').size().median()
        txt = f'{per_frame:.0f} droplets/frame, radius CV {recent.radius.std() / recent.radius.mean():.2f}'
        if 'sam_ok' in recent and recent.sam_ok.notna().any():
            txt += f', SAM rejects {(recent.sam_ok == 0).mean() / recent.sam_ok.notna().mean():.0%} of detections'
        return txt

    def qc_problem(self, drops):
        """A hard image check that pauses the loop whatever the planner or Muse would do. Looks at the last
        qc_window seconds of frames; returns what is wrong, or None."""
        frames = self.frames(drops)
        if not len(frames):
            return None  # nothing imaged yet: the worker starts a little after the screen
        t = self.now()
        if t - frames.time.max() > self.a.qc_stall:
            return f'no new frames for {t - frames.time.max():.0f} s (live worker stopped?)'
        recent_frames = frames[frames.time >= t - self.a.qc_window]
        if len(recent_frames) < 3:
            return None
        per_frame = recent_frames.n_droplets.median()
        if per_frame < self.a.qc_min_per_frame:
            return f'only {per_frame:.0f} droplets per frame in the last {self.a.qc_window:.0f} s'
        recent = drops[drops.time >= t - self.a.qc_window]
        if 'sam_ok' in recent:
            checked = recent.sam_ok.dropna()
            if len(checked) >= 20 and (checked == 0).mean() > self.a.qc_max_sam_reject:
                return (f'SAM rejects {(checked == 0).mean():.0%} of {len(checked)} detections in the last '
                        f'{self.a.qc_window:.0f} s: the camera is not seeing whole droplets')
        return None

    def protein_used(self, ev):
        """uL of protein pumped so far: each setpoint's protein flow until the next setpoint (or now)."""
        acc = ev[ev.event == 'accepted'].sort_values('time')
        if not len(acc):
            return 0.0
        times = acc.time.tolist() + [self.now()]
        stop = ev[ev.event == 'cancelled']
        used = 0.0
        for i, (_, r) in enumerate(acc.iterrows()):
            end = times[i + 1]
            if len(stop) and stop.time.max() > r.time:
                end = min(end, stop.time.max())
            used += float(r[str(PROTEIN_PUMP)]) * max(end - r.time, 0) / 3600
        return used

    # ------------------------------------------------------------------ one decision
    def step(self):
        ev = self.queue.events()
        if len(ev):
            ev = ev[ev.time >= self.started - 1]  # the queue's events.csv persists across runs: ignore earlier runs
        if not len(ev):
            ev = pd.DataFrame(columns=['time', 'event', 'id', 'hold_s'] + [str(p) for p in list(PUMPS) + [BUFFER]])
        drops = self.droplets()
        problem = self.qc_problem(drops)
        if problem:
            self.paused = True
            self.n += 1
            rec = dict(time=self.now(), decision=self.n, decided_by='QC check', action='pause', arg=problem,
                       observation=problem, rationale='Hard image check: no more setpoints until an operator looks.',
                       setpoint=None, flows=None, note='', protein_used_ul=round(self.protein_used(ev), 3),
                       results_back=None, in_flight=[], candidates=[])
            with open(self.log / 'decisions.jsonl', 'a') as f:
                f.write(json.dumps(rec, default=float) + '\n')
            return rec
        res = self.results(ev, drops)
        done = [r for r in res if r['frac'] is not None and not r['in_flight']]
        flight = [r for r in res if r['in_flight']]
        queued = [i for i in self.sent if i not in {r['id'] for r in res}]
        if len(flight) - sum(1 for r in flight if r['end'] is not None) + len(queued) >= self.a.depth:
            return None  # enough already holding or waiting in the queue

        used = self.protein_used(ev)
        cands = self.planner.propose([dict(x=r['x'], frac=r['frac'], n=r['n']) for r in done],
                                     [r['x'] for r in flight if r['x']] +
                                     [self.space.x(self.sent[i]).tolist() for i in queued], k=self.a.candidates)
        next_ul = cands[0]['flows'][PROTEIN_PUMP] * (self.a.hold + self.a.settle) / 3600
        budget = dict(used_ul=used, budget_ul=self.a.budget, reserve_ul=self.a.reserve, next_ul=next_ul,
                      names=list(PUMPS.values()))
        qc = dict(in_flight=[r['id'] for r in flight] + queued, summary=self.image_qc(drops))
        prompt = brief(self.a.question, budget, [r for r in res if r['x']], cands, qc)

        self.n += 1
        decision, record = self.muse.decide(prompt, len(cands), [r['id'] for r in res])
        decided_by = 'muse'
        if decision is None:
            decided_by = 'planner fallback'
            decision = dict(action='run_candidate', arg=0, observation='',
                            rationale=f'Muse unavailable ({record.get("muse_error")}); planner top candidate')

        flows, sp_id, note = None, None, ''
        if decision['action'] == 'run_candidate':
            flows = cands[decision['arg']]['flows']
        elif decision['action'] == 'replicate':
            flows = next(r['flows'] for r in res if r['id'] == str(decision['arg']))
        elif decision['action'] == 'pause':
            self.paused = True
        if flows is not None:
            cost = flows[PROTEIN_PUMP] * (self.a.hold + self.a.settle) / 3600
            if used + cost > self.a.budget - self.a.reserve:
                # the reserve is a hard limit: the controller refuses, whoever asked
                note = f'refused: {used:.2f} + {cost:.2f} uL would breach the {self.a.reserve:.2f} uL reserve'
                decided_by += ' -> controller'
                decision = dict(decision, action='finish', arg='protein budget reached')
                flows = None
        if flows is not None:
            sp_id = f'C{len(self.sent) + 1:02d}'
            self.queue.submit(sp_id, flows, self.a.hold)
            self.sent[sp_id] = flows

        rec = dict(time=self.now(), decision=self.n, decided_by=decided_by, action=decision['action'],
                   arg=decision['arg'], observation=decision.get('observation', ''),
                   rationale=decision.get('rationale', ''), setpoint=sp_id, flows=flows, note=note,
                   protein_used_ul=round(used, 3), results_back=len(done), in_flight=qc['in_flight'],
                   candidates=cands, **record)
        with open(self.log / 'decisions.jsonl', 'a') as f:
            f.write(json.dumps(rec, default=float) + '\n')
        if res:
            pd.DataFrame([dict(decision=self.n, **{k: v for k, v in r.items() if k != 'flows'}) for r in res]) \
                .to_csv(self.log / 'results.csv', mode='a', header=not (self.log / 'results.csv').exists(), index=False)
        self.write_map(done)
        return rec

    def write_map(self, done):
        """<log>/map.json (latest) and maps/map_<decision>.json: the GP phase map the PhasePilot tab draws."""
        try:
            m = phase_map(self.space, [dict(x=r['x'], frac=r['frac'], n=r['n']) for r in done])
        except Exception as e:  # display only: never stop the loop over it
            print(f'phase map failed: {e}', flush=True)
            return
        if m is None:
            return
        m.update(decision=self.n, time=self.now())
        (self.log / 'maps').mkdir(exist_ok=True)
        text = json.dumps(m)
        (self.log / 'maps' / f'map_{self.n:03d}.json').write_text(text)
        tmp = self.log / 'map.json.tmp'
        tmp.write_text(text)
        tmp.replace(self.log / 'map.json')

    def run(self, poll=2.0, max_decisions=None):
        while not self.paused:
            rec = self.step()
            if rec:
                print(f'[{rec["decision"]}] {rec["decided_by"]}: {rec["action"]} {rec["arg"]} -> {rec["setpoint"]} '
                      f'{rec["flows"]}  ({rec["protein_used_ul"]:.2f} uL used) {rec["note"]}', flush=True)
                if rec['action'] == 'pause':
                    return 'paused for operator'
                if rec['action'] == 'finish':
                    return 'finished'
                if max_decisions and rec['decision'] >= max_decisions:
                    return 'max decisions'
            time.sleep(poll)
        return 'paused for operator'


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--worker-out', required=True)
    p.add_argument('--queue', required=True)
    p.add_argument('--log', required=True)
    p.add_argument('--lag', type=float, default=180, help='s from generation to the imaging position')
    p.add_argument('--settle', type=float, default=20, help='s after a change before flows are steady')
    p.add_argument('--hold', type=float, default=60, help='s each setpoint is held')
    p.add_argument('--depth', type=int, default=1, help='setpoints to keep queued or holding')
    p.add_argument('--budget', type=float, default=30, help='uL of protein for the campaign')
    p.add_argument('--reserve', type=float, default=5, help='uL that must stay in the syringe')
    p.add_argument('--total', type=float, default=120, help='aqueous total, uL/h (sweep_totflow_4D)')
    p.add_argument('--fmin', type=float, default=2.5, help='minimum flow per pump, uL/h')
    p.add_argument('--step', type=float, default=0.05, help='grid step in flow fraction')
    p.add_argument('--warm', type=int, default=6, help='random settings before the GP takes over')
    p.add_argument('--candidates', type=int, default=5)
    p.add_argument('--min-droplets', type=int, default=20, help='classified droplets needed for a result')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--question', default=QUESTION, help='the question Muse is given (e.g. to say it is a dye rehearsal)')
    p.add_argument('--qc-window', type=float, default=60, help='s of recent frames the QC check looks at')
    p.add_argument('--qc-stall', type=float, default=90, help='pause if no new frame for this many s')
    p.add_argument('--qc-min-per-frame', type=float, default=5, help='pause below this many droplets per frame')
    p.add_argument('--qc-max-sam-reject', type=float, default=0.5, help='pause if SAM rejects more than this')
    p.add_argument('--max-decisions', type=int)
    return p


if __name__ == '__main__':
    a = parser().parse_args()
    if a.question.startswith('@'):  # --question @file: read it from a file (avoids shell quoting on the rig)
        a.question = Path(a.question[1:]).read_text().strip()
    print(Loop(a).run(max_decisions=a.max_decisions))
