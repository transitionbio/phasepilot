"""Planner side of the PhaseScan live setpoint queue.

The rig GUI (Cont Screen with `setpoint_queue_4D` set in the screen config) polls
<folder>/pending for *.json setpoints, applies and holds each one, then moves it to
done/ or rejected/ and appends to events.csv. This module writes those files and
reads the results, either on a local folder or on the rig over ssh.

    q = SetpointQueue.over_ssh('<rig-host>', '<rig>/queue')
    q.submit('B07', {4: 30, 2: 30, 3: 30, 1: 30}, hold_s=60)
    q.state()   # {'state': 'holding', 'id': 'B07', 'until': ...}
    q.events()  # DataFrame of accepted/rejected/done/cancelled with epoch times
"""
import io
import json
import os
import subprocess
import tempfile
import time

import pandas as pd


class SetpointQueue:
    def __init__(self, folder, host=None):
        self.folder = folder.rstrip('/\\')
        self.host = host
        self._n = 0

    @classmethod
    def over_ssh(cls, host, folder):
        return cls(folder, host)

    def submit(self, sp_id, flows, hold_s):
        """Queue one setpoint. flows: {pump index: ul/h}. Files run in name order, so the
        name starts with a timestamp and a counter."""
        self._n += 1
        name = f'{time.strftime("%Y%m%d_%H%M%S")}_{self._n:04d}_{sp_id}'
        body = json.dumps({'id': sp_id, 'hold_s': float(hold_s),
                           'flows': {str(k): float(v) for k, v in flows.items()}})
        # write *.tmp then rename, so the GUI never reads a half-written file
        if self.host is None:
            pending = os.path.join(self.folder, 'pending')
            os.makedirs(pending, exist_ok=True)
            tmp = os.path.join(pending, name + '.tmp')
            with open(tmp, 'w') as f:
                f.write(body)
            os.replace(tmp, os.path.join(pending, name + '.json'))
        else:
            with tempfile.NamedTemporaryFile('w', suffix='.tmp', delete=False) as f:
                f.write(body)
            try:
                subprocess.run(['scp', '-q', f.name, f'{self.host}:{self.folder}/pending/{name}.tmp'],
                               check=True, timeout=60)
                self._ps(f"Rename-Item '{self.folder}/pending/{name}.tmp' '{name}.json'")
            finally:
                os.unlink(f.name)
        return name

    def state(self):
        text = self._read('state.json')
        return json.loads(text) if text else None

    def events(self):
        text = self._read('events.csv')
        return pd.read_csv(io.StringIO(text)) if text else pd.DataFrame()

    def wait_for(self, sp_id, event='done', timeout=3600, poll_s=2):
        """Block until sp_id reaches `event` (or is rejected/cancelled); returns that events row."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            ev = self.events()
            if len(ev):
                rows = ev[(ev['id'].astype(str) == str(sp_id)) & ev['event'].isin([event, 'rejected', 'cancelled'])]
                if len(rows):
                    return rows.iloc[-1]
            time.sleep(poll_s)
        raise TimeoutError(f'setpoint {sp_id} did not reach {event} in {timeout} s')

    def _read(self, rel):
        if self.host is None:
            path = os.path.join(self.folder, rel)
            if not os.path.exists(path):
                return None
            with open(path) as f:
                return f.read()
        path = f'{self.folder}/{rel}'
        out = self._ps(f"if (Test-Path '{path}') {{ Get-Content -Raw '{path}' }}")
        return out or None

    def _ps(self, command):
        r = subprocess.run(['ssh', self.host, command], capture_output=True, text=True, timeout=60, check=True)
        return r.stdout.strip()
