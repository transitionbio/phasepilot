"""Build the ~30 s PhasePilot edit: four moments, plain captions, no title cards.

    python build_short.py --run runs/<stamp> --start <epoch of the recording's first frame> --out edit_short.json
Then:
    python cut_demo.py --raw recording/<mp4> --start <epoch> --decisions runs/<stamp>/log/decisions.jsonl \
        --edit edit_short.json --out phasepilot_30s.mp4

Moments: a Muse decision with its reasoning on screen (PhasePilot tab); a result landing and the planner's phase
map redrawing around it (PhasePilot tab); the live per-droplet phase diagrams filling in (Live analysis tab);
the QC pause and operator resume (PhasePilot tab).  Times are epochs from decisions.jsonl; each clip is placed
inside a window where the demo window showed the right tab (--cycle, PhasePilot:Live seconds).
"""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run', required=True)
    p.add_argument('--start', type=float, required=True)
    p.add_argument('--out', default='edit_short.json')
    p.add_argument('--cycle', default='60:25', help='demo_window tab cycle used for the recording')
    p.add_argument('--prefilter', default='', help='comma-separated ffmpeg filters applied to every clip first')
    a = p.parse_args()
    run = Path(a.run)
    decisions = [json.loads(l) for l in open(run / 'log/decisions.jsonl') if l.strip()]
    q = json.loads((run / 'log/question.json').read_text())
    on_pilot, on_live = (int(v) for v in a.cycle.split(':'))
    period = on_pilot + on_live

    def tab_window(t, tab):
        """[start, end] of the window of that tab containing t, or the next one."""
        k = int((t - q['set_at']) // period)
        for i in range(k, k + 3):
            s = q['set_at'] + i * period
            ws, we = (s, s + on_pilot) if tab == 'pilot' else (s + on_pilot, s + period)
            if we > t:
                return ws, we
        raise ValueError

    def on_pilot_tab(t0, t1):
        ws, we = tab_window(t0, 'pilot')
        return ws <= t0 and t1 <= we

    muse = [d for d in decisions if d['decided_by'] == 'muse' and d['action'] == 'run_candidate']
    pauses = [d for d in decisions if d['decided_by'] == 'QC check']
    resumes = [d for d in decisions if d['decided_by'] == 'operator']
    maps = sorted(run.glob('log/maps/map_*.json'))
    map_decisions = [json.loads(m.read_text())['decision'] for m in maps]

    # A: a Muse decision made with >= 2 results back, reasoning readable for ~9 s on the PhasePilot tab
    dA = next(d for d in muse if (d.get('results_back') or 0) >= 2 and on_pilot_tab(d['time'] + 1.5, d['time'] + 9.5))
    # B: a later decision at which a new result landed and the phase map was redrawn (map file written), tab on PhasePilot
    def alone(d, before, after):  # no other decision (e.g. a QC pause) inside the clip
        return not any(o is not d and d['time'] - before <= o['time'] <= d['time'] + after for o in decisions)
    def previous(d):
        return next((o for o in decisions if o['decision'] == d['decision'] - 1), None)
    # (the tab shows the previous decision's panel until this one lands, so that one must be Muse's too)
    dB = next(d for d in decisions if d['decided_by'] == 'muse' and d['decision'] > dA['decision']
              and d['decision'] in map_decisions and (d.get('results_back') or 0) > (dA.get('results_back') or 0)
              and on_pilot_tab(d['time'] - 2.5, d['time'] + 5.5) and alone(d, 2.5, 5.5)
              and previous(d) and previous(d)['decided_by'] == 'muse')
    # C: live analysis tab, late enough that the phase diagrams are populated (after decision B)
    ws, we = tab_window(dB['time'] + 5, 'live')
    cC = (ws + 2, min(ws + 7, we - 1))
    # D: first QC pause to the last operator resume, compressed
    tD0 = pauses[0]['time'] + 1.5
    tD1 = min(resumes[-1]['time'] + 4.5, tab_window(tD0, 'pilot')[1])  # stay on the PhasePilot tab
    speedD = max(2, round((tD1 - tD0) / 7))  # ~7 s on screen
    # the resume, if it fell outside that window: first PhasePilot window after it, before the next decision
    tR = resumes[-1]['time']
    tail = None
    if tR + 2 > tD1:
        ws, we = tab_window(tR, 'pilot')
        ws = max(ws, tR + 0.5)
        following = [o['time'] for o in decisions if o['time'] > tR + 0.5]
        we = min(we, ws + 3, (following[0] - 0.5) if following else we)
        if we - ws >= 1.5:
            tail = (ws, we)
    seq = [
        dict(**{'from': dA['time'] + 1.5, 'to': dA['time'] + 9.5}, speed=1,
             caption='Muse reads the results so far and picks the next condition, with its reasoning'),
        dict(**{'from': dB['time'] - 2.5, 'to': dB['time'] + 5.5}, speed=1,
             caption='A result lands and the planner redraws the phase map and its predicted boundary'),
        dict(**{'from': cC[0], 'to': cC[1]}, speed=1,
             caption='Live analysis: every droplet classified and placed on the phase diagrams as it is imaged'),
        dict(**{'from': tD0, 'to': tD1}, speed=speedD,
             caption='Empty channel: SAM rejects every droplet, the loop pauses until the operator resumes'),
    ]
    if tail:
        seq.append(dict(**{'from': tail[0], 'to': tail[1]}, speed=1,
                        caption='The operator resumes and the loop carries on'))
    edit = {'cards': {}, 'sequence': seq}
    if a.prefilter:
        edit['prefilter'] = a.prefilter.split(',')
    Path(a.out).write_text(json.dumps(edit, indent=1))
    total = sum((x['to'] - x['from']) / x['speed'] for x in seq)
    print(f'{len(seq)} clips, ~{total:.1f} s; A = decision {dA["decision"]}, B = decision {dB["decision"]} '
          f'(map after {map_decisions}), C = live {cC[0]:.0f}-{cC[1]:.0f}, D = {tD0:.0f}-{tD1:.0f}')


if __name__ == '__main__':
    main()
