"""End-to-end test of the rig loop with the hardware simulated, time compressed ~100x.

  GUI      the real queue_flowscan from Beta_Screen_Control.py, on fake pumps
  camera   a thread writing live-worker part files: droplets imaged now were made `lag` ago, so their
           PS probability comes from the flows active then and a hidden boundary; 5% fail SAM QC
  Muse     a local OpenAI-compatible server standing in for the provider: replies run_candidate 0,
           a replicate, then one invalid reply, then goes down (HTTP 500) - the loop must log a planner
           fallback for those, never crash
Checks: setpoints flow through queue -> GUI -> pumps, results are matched to the right setpoint after the lag,
every decision is logged with who made it, the reserve stops the campaign, nothing breaks the instrument limits.
"""
import asyncio
import http.server
import json
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from driver import Loop, PUMPS, parser  # noqa: E402
from muse import MuseClient  # noqa: E402
from test_queue import FakeScreen, Pump, load_methods  # noqa: E402

LAG, HOLD, SETTLE = 1.5, 1.0, 0.3


def hidden_ps(f):
    """PS probability for flows {pump: uL/h}: phase separates with enough G3BP1 and PEG."""
    g, peg = f.get(3, 0) / 120, f.get(1, 0) / 120
    return 1 / (1 + np.exp(-(g + 0.8 * peg - 0.45) * 25))


class FakeMuse(http.server.BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        FakeMuse.calls.append(body)
        n = len(FakeMuse.calls)
        if n >= 6:
            self.send_response(500)
            self.end_headers()
            return
        if n == 3:
            reply = {'reasoning': 'C01 is the only result back and sits near the predicted boundary. A repeat costs '
                                  'one more setpoint of protein but tells us whether it was noise.',
                     'observation': 'C01 came back mostly mixed.', 'action': 'replicate', 'arg': 'C01',
                     'rationale': 'Check C01 holds up before moving on.'}
        elif n == 4:
            reply = {'action': 'set_pressure', 'arg': 900}  # not a supported action
        else:
            reply = {'observation': 'Boundary still uncertain.', 'action': 'run_candidate', 'arg': 0,
                     'rationale': 'Top candidate is the most informative.'}
        out = json.dumps({'model': body['model'], 'choices': [{'message': {'content': json.dumps(reply)}}]})
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(out.encode())

    def log_message(self, *a):
        pass


def main():
    root = tempfile.mkdtemp()
    qdir, wout, logd = (os.path.join(root, d) for d in ('queue', 'worker', 'log'))
    os.makedirs(wout)

    # GUI side: real queue_flowscan on fake pumps, in its own event loop thread
    m = load_methods(['queue_flowscan', 'check_setpoints_4D'])
    s = FakeScreen()
    s.main_UI = SimpleNamespace(logger=__import__('logging').getLogger('gui'))
    s.sweep_channels_4D, s.sweep_totflow_4D, s.continuous_scan_flag = [4, 2, 3, 1], 120, True
    sets = []
    s.pumps = {ch: Pump(sets, ch) for ch in range(5)}
    s.check_setpoints_4D = m['check_setpoints_4D'].__get__(s)
    gui_loop = asyncio.new_event_loop()
    gui_task = gui_loop.create_task(m['queue_flowscan'].__get__(s)(qdir, poll_s=0.05))
    threading.Thread(target=gui_loop.run_until_complete, args=(gui_task,), daemon=True).start()

    # camera + live worker: droplets imaged now were made LAG s ago
    stop = threading.Event()
    rng = np.random.default_rng(1)

    def flows_at(t):
        cur = {}
        for when, ch, v in sets:
            if when <= t:
                cur[ch] = v
        return cur

    def camera():
        k = 0
        while not stop.is_set():
            t = time.time()
            f = flows_at(t - LAG)
            n = 40
            p = hidden_ps(f) if f else 0.0
            d = pd.DataFrame({'frame': k, 'time': t, 'x': 0, 'y': 0, 'radius': rng.normal(40, 2, n),
                              'phase_separated_prob': np.where(rng.random(n) < p, 0.97, 0.03),
                              'sam_ok': (rng.random(n) > 0.05).astype(float)})
            d.to_parquet(os.path.join(wout, f'.part_{k:05d}.parquet'))
            os.replace(os.path.join(wout, f'.part_{k:05d}.parquet'), os.path.join(wout, f'part_{k:05d}.parquet'))
            k += 1
            time.sleep(0.1)

    threading.Thread(target=camera, daemon=True).start()

    srv = http.server.HTTPServer(('127.0.0.1', 0), FakeMuse)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    muse = MuseClient(base_url=f'http://127.0.0.1:{srv.server_port}', model='meta/muse-test', api_key='test')

    a = parser().parse_args(['--worker-out', wout, '--queue', qdir, '--log', logd, '--lag', str(LAG),
                             '--settle', str(SETTLE), '--hold', str(HOLD), '--budget', '0.12',
                             '--reserve', '0.02', '--warm', '3', '--min-droplets', '10'])
    loop = Loop(a, muse=muse)
    outcome = loop.run(poll=0.1, max_decisions=40)
    time.sleep(HOLD + 0.5)
    s.continuous_scan_flag = False
    stop.set()
    time.sleep(0.8)

    recs = [json.loads(line) for line in open(os.path.join(logd, 'decisions.jsonl'))]
    ev = pd.read_csv(os.path.join(qdir, 'events.csv'))
    for r in recs:
        print(f'{r["decision"]:2d} {r["decided_by"]:<28} {r["action"]:<13} {str(r["arg"]):<24} {r["setpoint"]} '
              f'used {r["protein_used_ul"]:.3f}  back {r["results_back"]}  {r.get("muse_error", "")[:50]}')
    print('outcome:', outcome)

    by = [r['decided_by'] for r in recs]
    assert by[:3] == ['muse'] * 3, by
    assert recs[2]['action'] == 'replicate' and recs[2]['flows'] == recs[0]['flows']
    assert 'costs' in recs[2]['muse_reasoning'], recs[2].get('muse_reasoning')  # Muse's reasoning is kept
    assert by[3] == 'planner fallback' and 'unsupported action' in recs[3]['muse_error']
    assert all(b.startswith('planner fallback') for b in by[5:]) and 'HTTPError 500' in recs[6]['muse_error']
    assert outcome == 'finished' and 'controller' in by[-1] and 'reserve' in recs[-1]['note']
    assert recs[-1]['protein_used_ul'] <= 0.12 - 0.02 + 0.01
    sent = [r for r in recs if r['setpoint']]
    accepted = ev[ev.event == 'accepted']
    assert list(accepted.id) == [r['setpoint'] for r in sent], (list(accepted.id), [r['setpoint'] for r in sent])
    assert ev[ev.event == 'rejected'].empty
    for r in sent:
        assert abs(sum(r['flows'].values()) - 120) < 0.05 and min(r['flows'].values()) >= 2.5 - 1e-6
    # results matched after the lag: PS fraction tracks the hidden boundary at the flows that were set
    res = pd.read_csv(os.path.join(logd, 'results.csv')).drop_duplicates('id', keep='last').dropna(subset=['frac'])
    truth = [hidden_ps({int(k): v for k, v in next(r['flows'] for r in sent if r['setpoint'] == i).items()})
             for i in res.id]
    err = np.abs(res.frac.to_numpy() - np.array(truth))
    print(f'{len(res)} results back; |PS frac - truth| median {np.median(err):.2f}, max {err.max():.2f}')
    assert np.median(err) < 0.15
    print('OK')


if __name__ == '__main__':
    main()
