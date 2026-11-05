"""Exercise the GUI's queue_flowscan against setpoint_queue.SetpointQueue without the rig.

Pulls queue_flowscan and check_setpoints_4D out of Beta_Screen_Control.py (the module itself
needs the Fluigent SDK and the rest of the GUI) and runs them on a fake screen object.
"""
import ast
import asyncio
import csv
import json
import logging
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from setpoint_queue import SetpointQueue

SRC = os.path.expanduser('~/PhaseScan-Beta-control/phasecontrol/Screen_Control_Functions/Beta_Screen_Control.py')


def load_methods(names):
    tree = ast.parse(open(SRC).read())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    funcs = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    ns = {'np': np, 'os': os, 'csv': csv, 'json': json, 'time': time, 'asyncio': asyncio}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), SRC, 'exec'), ns)
    return {n: ns[n] for n in names}


class Pump:
    def __init__(self, log, ch):
        self.log, self.ch = log, ch

    def flow(self, v):
        self.log.append((round(time.time(), 1), self.ch, v))


class FakeScreen:
    pass


async def main():
    m = load_methods(['queue_flowscan', 'check_setpoints_4D'])
    s = FakeScreen()
    s.main_UI = type('UI', (), {'logger': logging.getLogger('gui')})()
    s.sweep_channels_4D = [4, 2, 3, 1]
    s.sweep_totflow_4D = 120
    s.continuous_scan_flag = True
    sets = []
    s.pumps = {ch: Pump(sets, ch) for ch in range(5)}
    s.check_setpoints_4D = m['check_setpoints_4D'].__get__(s)
    run = m['queue_flowscan'].__get__(s)

    folder = tempfile.mkdtemp()
    q = SetpointQueue(folder)
    task = asyncio.create_task(run(folder, poll_s=0.05))
    await asyncio.sleep(0.2)
    assert q.state()['state'] == 'waiting'

    q.submit('A1', {4: 30, 2: 30, 3: 30, 1: 30}, hold_s=0.3)
    q.submit('bad_total', {4: 30, 2: 30, 3: 30, 1: 50}, hold_s=0.3)
    q.submit('bad_neg', {4: -5, 2: 55, 3: 40, 1: 30}, hold_s=0.3)
    q.submit('B1', {4: 2.5, 2: 2.5, 3: 112.5, 1: 2.5}, hold_s=0.3)
    with open(os.path.join(folder, 'pending', 'zz_garbage.json'), 'w') as f:
        f.write('{not json')
    await asyncio.sleep(0.15)
    assert q.state() == {**q.state(), 'state': 'holding', 'id': 'A1'}, q.state()
    await asyncio.sleep(1.0)
    q.submit('C1', {4: 60, 2: 20, 3: 20, 1: 20}, hold_s=5)
    await asyncio.sleep(0.3)
    task.cancel()  # Stop button mid-hold
    try:
        await task
    except asyncio.CancelledError:
        pass

    ev = q.events()
    print(ev.to_string())
    got = list(zip(ev['event'], ev['id']))
    assert got == [('accepted', 'A1'), ('done', 'A1'), ('rejected', 'bad_total'), ('rejected', 'bad_neg'),
                   ('accepted', 'B1'), ('done', 'B1'), ('rejected', 'zz_garbage'),
                   ('accepted', 'C1'), ('cancelled', 'C1')], got
    assert q.state()['state'] == 'stopped'
    assert os.listdir(os.path.join(folder, 'pending')) == []
    assert len(os.listdir(os.path.join(folder, 'rejected'))) == 3
    assert [v for _, ch, v in sets if ch == 3] == [30, 112.5, 20]
    assert not any(ch == 0 for _, ch, _ in sets)  # oil untouched by the queue
    a1 = ev[ev['id'] == 'A1']['time'].to_numpy()
    assert 0.25 < a1[1] - a1[0] < 0.5, a1
    print('OK')


if __name__ == "__main__":
    asyncio.run(main())
