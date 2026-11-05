"""PhasePilot demo on recorded data: the closed loop, with the instrument and camera replayed from a real run.

What is real and what is replayed
  REPLAYED  the instrument: the GUI's own setpoint-queue code (queue_flowscan) runs on simulated pumps, and the
            camera answers each setpoint with the recorded frames whose droplet composition (from the pipeline's
            barcode read-out) is nearest to the composition requested. Data: PhaseScan Beta3, 2026-10-28,
            G3BP1 / PolyA RNA / PEG. Time is compressed (short holds, short lag).
  LIVE      the live analysis worker (pipeline CNN + Meta's SAM on every recorded frame it is given), the Bayesian
            planner, Muse (muse-spark-1.3 through Meta's Model API) and the controller checks.
  INJECTED  one QC fault (--fault): for one setpoint the camera serves frames of an empty channel (Beta3,
            2026-10-30), so SAM rejects every detection and the hard QC check pauses the loop until the
            operator resumes. It is logged as injected.

Run folder layout: queue/ (GUI side), frames/ (camera), worker_out/ (live analysis), log/ (decisions).
Starts when the demo window writes log/question.json (the scientist's question, budget and reserve).

    python orchestrate.py --run-dir /tmp/pp_demo --fault C06
"""
import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'loop'))
from driver import BUFFER, PROTEIN_PUMP, PUMPS, Loop, parser as driver_parser  # noqa: E402
from muse import MuseClient, SYSTEM as MUSE_SYSTEM  # noqa: E402
from planner import Planner, Space  # noqa: E402
from setpoint_queue import SetpointQueue  # noqa: E402
from test_queue import FakeScreen, Pump, load_methods  # noqa: E402

RAW = HERE.parent / 'live_demo' / 'raw_pos0'
COMPOSITION = HERE / 'data' / 'frames_composition.csv'
FAULT_FRAMES = sorted((HERE / 'data' / 'fault_frames').glob('frame_*.npy'))
ASSETS = HERE / 'assets'   # dark/fluors calibration stacks, CNN weights, SAM checkpoint (see README)
SAM = ASSETS / 'sam_vit_b_01ec64.pth'
WORKER_PY = Path.home() / 'anaconda3/envs/phasescan-cloud/bin/python'
REPO = Path.home() / 'PhaseScan-Beta-control'
RUN_CONFIG = HERE.parent / 'live_demo' / 'run_config'

DATA_NOTE = ('Replay of the recorded PhaseScan Beta3 run of 2026-10-28 (G3BP1 / PolyA RNA / PEG). '
             'Instrument and camera simulated from recorded frames; SAM, planner and Muse live.')


class RecordedRun:
    """The recorded run as a lookup: requested composition -> frames whose droplets were nearest to it."""

    def __init__(self):
        table = pd.read_csv(COMPOSITION)
        table = table[table.frame >= 60]  # the first recorded frames are still packing: many partial droplets
        self.frames = table.frame.to_numpy()
        self.X = table[['g3bp1', 'polya', 'peg']].to_numpy()   # same order as PUMPS: G3BP1, PolyA, PEG

    def nearest(self, x, k):
        distance = np.linalg.norm(self.X - np.asarray(x, float), axis=1)
        order = np.argsort(distance)[:k]
        return [int(self.frames[i]) for i in order], float(distance[order[0]])

    def allowed(self, G, radius):
        return np.sqrt(((G[:, None, :] - self.X[None, :, :]) ** 2).sum(-1)).min(1) <= radius


def flows_at(sets, t):
    """Pump flows {pump: uL/h} that the simulated pumps were holding at time t."""
    current = {}
    for when, channel, value in sets:
        if when <= t:
            current[channel] = value
    return current or None


def camera(stop, run, sets, frames_dir, args, fault_id, accepted):
    """Writes frames/frame_<n>.npy every --frame-every s: the recorded frames nearest to the composition the
    pumps were set to --lag s earlier (the time droplets take to reach the imaging position)."""
    space = Space(PUMPS, BUFFER, total=args.total, fmin=args.fmin, step=args.step)
    frames_dir.mkdir(exist_ok=True)
    n, cycle, last_key = 0, 0, None
    while not stop.is_set():
        t = time.time()
        flows = flows_at(sets, t - args.lag)
        key = tuple(sorted(flows.items())) if flows else None
        if key != last_key:
            cycle, last_key = 0, key
        active = accepted(t - args.lag)
        if fault_id and active == fault_id and FAULT_FRAMES:
            source = FAULT_FRAMES[cycle % len(FAULT_FRAMES)]
        else:
            x = space.x({p: flows.get(p, 0) for p in PUMPS}) if flows else run.X[0]
            candidates, _ = run.nearest(x, args.frames_per_setpoint)
            source = RAW / f'frame_{candidates[cycle % len(candidates)]:04d}.npy'
        target = frames_dir / f'frame_{n:04d}.npy'
        try:
            os.link(source, frames_dir / f'.frame_{n:04d}.npy')  # same filesystem: no disk cost per frame
        except OSError:
            shutil.copy(source, frames_dir / f'.frame_{n:04d}.npy')
        os.replace(frames_dir / f'.frame_{n:04d}.npy', target)
        os.utime(target, (t, t))
        (frames_dir / 'sources.csv').open('a').write(f'{n},{t:.3f},{source.name},{active or ""}\n')
        n += 1
        cycle += 1
        stop.wait(args.frame_every)


def start_gui(queue_dir):
    """The GUI's real queue_flowscan on simulated pumps, in its own event-loop thread."""
    methods = load_methods(['queue_flowscan', 'check_setpoints_4D'])
    screen = FakeScreen()
    screen.main_UI = type('UI', (), {'logger': logging.getLogger('gui')})()
    screen.sweep_channels_4D, screen.sweep_totflow_4D, screen.continuous_scan_flag = [4, 2, 3, 1], 120, True
    sets = []
    screen.pumps = {channel: Pump(sets, channel) for channel in range(5)}
    screen.check_setpoints_4D = methods['check_setpoints_4D'].__get__(screen)
    loop = asyncio.new_event_loop()
    task = loop.create_task(methods['queue_flowscan'].__get__(screen)(str(queue_dir), poll_s=0.2))
    threading.Thread(target=loop.run_until_complete, args=(task,), daemon=True).start()
    return screen, sets


def start_worker(frames_dir, out_dir, args):
    env = {**os.environ, 'PYTHONNOUSERSITE': '1'}
    model = next(ASSETS.glob('model/**/*_val.pth'))
    command = [str(WORKER_PY), '-m', 'phasecontrol.Live_Analysis.live_worker', '--frames-dir', str(frames_dir),
               '--config-common', str(RUN_CONFIG / 'config_common.yaml'),
               '--config-droplets', str(RUN_CONFIG / 'config_droplets.yaml'),
               '--background', str(ASSETS / 'dark.ome.tif'), '--illumination', str(ASSETS / 'fluors.ome.tif'),
               '--model', str(model), '--out', str(out_dir), '--sam-checkpoint', str(SAM),
               '--sam-every', str(args.sam_every), '--classify-per-frame', '10', '--batch', '2',
               '--threads', str(args.threads), '--idle-exit', '900']
    log = open(out_dir.parent / 'worker.log', 'a')
    return subprocess.Popen(command, cwd=str(REPO), env=env, stdout=log, stderr=subprocess.STDOUT)


def append(log_dir, record):
    with open(log_dir / 'decisions.jsonl', 'a') as f:
        f.write(json.dumps(record, default=float) + '\n')


def muse_summary(muse, loop, log_dir):
    """Beat 11: Muse writes up what the campaign taught, what it cost and what stays uncertain."""
    events = loop.queue.events()
    results = loop.results(events, loop.droplets())
    names = list(PUMPS.values())
    rows = []
    for r in results:
        if r['x']:
            frac = 'n/a' if r['frac'] is None else f'{r["frac"]:.2f}'
            rows.append(f'{r["id"]}: ' + ', '.join(f'{n} {v:.2f}' for n, v in zip(names, r['x'])) +
                        f' -> PS fraction {frac} ({r["n"]} droplets) {r["qc"]}')
    used = loop.protein_used(events)
    prompt = (f'The campaign has ended. Protein (G3BP1 stock) used: {used:.2f} uL of the {loop.a.budget:.1f} uL budget '
              f'({loop.a.reserve:.1f} uL reserve kept).\nRESULTS (composition = flow fraction of the aqueous total):\n'
              + '\n'.join(rows) +
              '\n\nWrite the closing summary for the scientist as JSON: {"learned": "<2-3 sentences: where droplets '
              'phase separated and where they stayed mixed, and where the boundary appears to lie>", '
              '"cost": "<1 sentence: protein used vs budget>", "uncertain": "<1-2 sentences: which region or '
              'result is least certain and what to test next>"}')
    text, served_by, secs, _ = muse.chat(MUSE_SYSTEM, prompt)
    append(log_dir, dict(time=time.time(), decision=loop.n + 1, decided_by='muse', action='summary', arg='',
                         observation=text, rationale='', setpoint=None, flows=None, note='campaign summary',
                         protein_used_ul=round(used, 3), results_back=len([r for r in results if r['frac'] is not None]),
                         in_flight=[], candidates=[], prompt=prompt, muse_reply=text, muse_served_by=served_by,
                         muse_seconds=round(secs, 1), muse_model=muse.model))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--run-dir', required=True)
    p.add_argument('--hold', type=float, default=25)
    p.add_argument('--settle', type=float, default=4)
    p.add_argument('--lag', type=float, default=40, help='simulated s from pumps to camera')
    p.add_argument('--frame-every', type=float, default=5)
    p.add_argument('--frames-per-setpoint', type=int, default=6, help='nearest recorded frames served per setpoint')
    p.add_argument('--sam-every', type=int, default=4)
    p.add_argument('--threads', type=int, default=14)
    p.add_argument('--fault', help='setpoint id that gets empty-channel frames (injected QC fault)')
    p.add_argument('--resume-after', type=float, default=25, help='s the "operator" takes to resume after a pause')
    p.add_argument('--allowed-radius', type=float, default=0.06, help='planner may only propose compositions this '
                   'close (flow fraction) to one the recorded run covered')
    p.add_argument('--no-muse', action='store_true', help='planner only (dry run)')
    p.add_argument('--max-decisions', type=int, default=40)
    p.add_argument('--total', type=float, default=120)
    p.add_argument('--fmin', type=float, default=2.5)
    p.add_argument('--step', type=float, default=0.05)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

    run_dir = Path(args.run_dir)
    queue_dir, frames_dir, out_dir, log_dir = (run_dir / d for d in ('queue', 'frames', 'worker_out', 'log'))
    for d in (queue_dir, frames_dir, out_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)
    (run_dir / 'DATA_NOTE.txt').write_text(DATA_NOTE + '\n')

    question_file = log_dir / 'question.json'
    logging.info('waiting for %s (the scientist sets the question in the demo window)', question_file)
    while not question_file.exists():
        time.sleep(0.5)
    q = json.loads(question_file.read_text())
    logging.info('question: %s', q)

    recorded = RecordedRun()
    screen, sets = start_gui(queue_dir)
    accepted_log = []  # (time, id) from the queue's events, for the camera's fault lookup

    def accepted(t):
        events = SetpointQueue(str(queue_dir)).events()
        if not len(events):
            return None
        acc = events[(events.event == 'accepted') & (events.time <= t)]
        return str(acc.id.iloc[-1]) if len(acc) else None

    stop = threading.Event()
    threading.Thread(target=camera, args=(stop, recorded, sets, frames_dir, args, args.fault, accepted),
                     daemon=True).start()
    worker = start_worker(frames_dir, out_dir, args)
    logging.info('camera and live worker started')

    a = driver_parser().parse_args([
        '--worker-out', str(out_dir), '--queue', str(queue_dir), '--log', str(log_dir),
        '--lag', str(args.lag), '--settle', str(args.settle), '--hold', str(q.get('hold_s', args.hold)),
        '--budget', str(q['budget_ul']), '--reserve', str(q['reserve_ul']), '--warm', '4',
        '--min-droplets', '15', '--qc-max-sam-reject', '0.75', '--qc-window', '45', '--qc-stall', '240',
        '--total', str(args.total), '--fmin', str(args.fmin), '--step', str(args.step),
        '--question', q['question'] + ' ' + DATA_NOTE + ' Each setpoint is answered with the recorded droplets '
        'imaged nearest to the requested composition.'])
    muse = MuseClient()
    if args.no_muse:
        muse.api_key = None  # every decision then falls back to the planner
    loop = Loop(a, queue=SetpointQueue(str(queue_dir)), muse=muse)
    loop.planner = Planner(loop.space, warm=a.warm, seed=a.seed,
                           allowed=recorded.allowed(loop.space.G, args.allowed_radius))
    run_json = json.loads((log_dir / 'run.json').read_text())
    run_json.update(data_note=DATA_NOTE, replay=True, fault=args.fault)
    (log_dir / 'run.json').write_text(json.dumps(run_json, indent=1))

    while True:
        outcome = loop.run(poll=1.0, max_decisions=args.max_decisions)
        logging.info('loop: %s', outcome)
        if outcome != 'paused for operator':
            break
        time.sleep(args.resume_after)
        loop.n += 1
        append(log_dir, dict(time=time.time(), decision=loop.n, decided_by='operator', action='resume', arg='',
                             observation='Operator checked the instrument and resumed the loop.',
                             rationale=('Injected fault: the camera was served frames of an empty channel for one '
                                        'setpoint to exercise the QC path.' if args.fault else ''),
                             setpoint=None, flows=None, note='', protein_used_ul=None, results_back=None,
                             in_flight=[], candidates=[]))
        loop.paused = False

    # let the last setpoints' droplets arrive and be analysed before the summary
    time.sleep(args.lag + args.hold + 30)
    if not args.no_muse:
        try:
            muse_summary(muse, loop, log_dir)
        except Exception as error:  # the summary is a nicety; the run is already logged
            logging.warning('summary failed: %r', error)
    screen.continuous_scan_flag = False
    time.sleep(10)
    stop.set()
    (run_dir / 'DONE').write_text(outcome)
    logging.info('done: %s', outcome)
    if worker.poll() is None:
        worker.terminate()


if __name__ == '__main__':
    main()
