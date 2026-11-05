"""Ask Muse Wonder (Meta Model API, muse-wonder-1.0) to re-direct the PhasePilot film in the Transition Bio style.

It gets the current film beat by beat (what is on screen, every word of card text, the measured numbers, the
footage that exists) and the style rules, and must return a JSON plan: the same content, 180 s, its own pacing,
headings, bullets, notes, presenter lines, and optional muse-image prompts for artwork. build_muse.py renders it.

    python muse_director.py --out muse/plan.json
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = dict(l.strip().split('=', 1) for l in open(HERE.parent / 'loop/.env') if '=' in l)
BASE = ENV.get('MUSE_BASE_URL', 'https://api.meta.ai/v1')
MODEL = 'muse-wonder-1.0'

BRIEF = """You are the creative director for a 3-minute demo film. Audience: the judging panel of the Muse hackathon
(Meta). The film is for Transition Bio (Cambridge, UK) and presents PhasePilot: a closed loop in which Muse (muse-spark-1.3)
chooses the next setpoint on a PhaseScan microfluidic rig, Segment Anything (SAM ViT-B) checks every droplet image, and a
Bayesian planner keeps the phase map. The presenters talk over the film live (no voice track in the file).

STYLE (Transition Bio template): white or very light backgrounds, Arial, headings in blue #1366AB, accents and key lines in
green #008759, body text dark grey #404040, muted grey #6E7276, light-blue panels #DBEFF9 with rounded corners, the
Transition Bio logo top-left, and a title/end background of blue water bubbles. Real lab footage and real dashboard
recordings may keep their own look. The style may change slightly from the current cut but must stay Transition Bio.

FOOTAGE AND ASSETS THAT EXIST (you can only use these; you cannot invent new footage):
  A. "explainer": Will's animated explainer (light theme, serif, 87.5 s, no audio). Beats with source times:
     0-6 condensates help organise the cell; 6-14 protein phase separation; 14-22 every protein has its own phase diagram;
     22-28 PhaseScan tiles (DO NOT USE, two image tiles are blank); 28.5-32.5 one droplet = 100 pL, ~1,000,000x less
     protein per data point (animated counter); 32-42 every new dimension multiplies the work (k^n curve, past four or
     five parameters a comprehensive scan is impossible); 42-50 so we handed the experiment to Muse (loop diagram);
     50-58 SAM 3.1 reads every droplet, live; 58-65.4 sampling goes where the information is (Bayesian model);
     65.5-72 the result (placeholder [X]/[Y], DO NOT USE); 72-78 biology is high-dimensional; 79.5-87.5 one closed loop,
     any parameter space. It can be played slower (up to 1.4x) so reveals are readable.
  B. "phone": portrait phone video shot in the lab today, 44 s: 2-12 the PhasePilot dashboard on the rig monitor during
     the live run; 15-44 the Beta3 rig (exterior, door opening, syringe pumps, chip stage, wide shot). Shown full height
     over a blurred background with a Transition Bio side panel (heading + up to 3 bullets + note).
  C. "loop": our dashboard film, four beats with source times: dash 3-9 (the real dashboard, four panels numbered:
     decisions, Muse reasoning, SAM QC, results+map); sam 9-20 (SAM outlines on real droplet frames, green accepted /
     red rejected); muse 20-32 (dashboard with Muse's panel boxed, then Muse's written reasoning readable);
     map 32-52 (the planner's phase map redrawing as results land, predicted boundary dashed). Each can play 0.8x-1.2x.
  D. Cards you can write: "title", "end", "results", and "card" (heading + up to 3 bullets + note on a white page
     with optional artwork from muse-image on the right). Any text you write is rendered in Arial by our builder.

MEASURED RESULTS (keep every number exactly; these are the content):
  - 20x less protein to map the phase boundary: 2.5 uL instead of 52 uL.
  - 17x less instrument run time: pumps and camera busy 2.9 min instead of 51 min. The loop's wall clock was 23 min
    because each of its 7 rounds waited 180 s for droplets to incubate before the next decision while the pumps idled;
    keeping droplets flowing through that wait brings wall clock down to the instrument time.
  - +1 variable mapped in the same instrument time and protein at 10 levels per variable; +2 variables at 4 levels per
    variable (a 17x saving buys log_k(17) extra dimensions, at every n). A raster costs k^n conditions; the loop samples
    the boundary, a surface of n-1 dimensions, ~k^(n-1).
  - Source: 3-variable replay (G3BP1 / TDP-43 / RNA, 180 s incubation), boundary accuracy at or above 0.997 vs the full scan.
  - Live run today: G3BP1 / PolyA RNA / PEG on Beta3, 4 November 2026. Muse chose each setpoint from the live evidence
    and explained why; SAM outlined every droplet; a result only counts when the image passes.
  - Biology is high n: protein, RNA, crowder, salt, pH, compound, temperature.
  The results beat always includes our scaling chart (instrument hours vs number of variables, raster vs loop, guides
  at 1 hour / working day / week / month) on the right; you write the stats and notes on the left.

CURRENT CUT (180 s) for reference, in order: title 4 s; explainer 0-22.5 at 1.25x; phone rig 15-24 ("PhaseScan: the
instrument": Beta3 microfluidic rig at Transition Bio / syringe pumps mix protein, RNA, crowder and buffer on a chip /
every droplet is 100 picolitres and one experimental condition); phone rig 30-39 ("Droplets as experiments": droplets
are imaged in three fluorescence channels as they flow past the camera / a CNN calls each droplet mixed or phase
separated, live / about a million times less protein per data point than plate-based labware); explainer 28.5-65.4 at
1.15x; phone dashboard 2-9 ("Today on the rig: the loop, live"); loop dash 1.1x, sam 0.85x, muse 1.0x, map 1.0x;
results 18 s; explainer 79.5-87.5 at 1.15x; end card 5 s ("One closed loop per protein: PhaseScan runs it, SAM checks
it, Muse decides." / "Built for the Muse hackathon, November 2026" / credits line).

YOUR JOB: re-direct this as a fluent 180.0 s film with the same content and the Transition Bio style. You may reorder,
retime, rewrite headings/bullets/notes, add short cards, and ask for artwork. Rules: total duration exactly 180.0 s
(sum of your beats); headings at most 30 characters; bullets at most 95 characters, at most 3 per card; notes at most
140 characters; keep every measured number; the results beat is at least 16 s; no beat shorter than 4 s; do not use
explainer 22-28.5 or 65.5-72; each beat gets a one-sentence "presenter" line the speakers can say over it.

PRESENTER FEEDBACK (treat as hard rules):
  - The explainer at 1.0x was too fast to read and talk over: play every explainer beat 1.15x-1.3x slower.
  - The rig footage works at about 9 s per beat. Write your own card wording, do not copy the current cut verbatim.
  - The results had too much on one slide. They are now TWO beats: "results_stats" (three big numbers, revealed one at
    a time so the speaker can read each live; keep line and sub short) followed by "results_chart" (the linear scaling
    chart, large: legacy scan vs PhasePilot in instrument days against variables mapped, 36 days vs 2 days at six
    variables; you write one short line and a short sub next to it, and one green line under it). Together at least 20 s.
  - Drop the wall-clock detail entirely (no mention of 23 min, 180 s incubation or idle pumps).
  - The scaling beat of the explainer (source 36.5-42) now carries the dark version's extra line, "Time is proportional
    to t0^N for N dimensions", drawn automatically when your explainer beat covers it, so include 32-42 in one beat.
  - Close with the explainer's multi-dimensional biology animation fading into the broader application space:
    use explainer 72-87.5 as ONE beat (nodes diagram 72-78, "one closed loop, any parameter space" 79.5-87.5), slowed,
    then the end card. Do not add a separate "biology is high-n" card; the animation covers it.

Reply with JSON only, no prose, in this schema:
{"title": "...", "beats": [
  {"type": "title", "seconds": 4, "heading": "PhasePilot", "subtitle": "...", "presenter": "..."},
  {"type": "explainer", "ss": 0, "len": 22.5, "slow": 1.25, "presenter": "..."},
  {"type": "phone", "ss": 15, "seconds": 9, "heading": "...", "bullets": ["...", "..."], "note": "...", "presenter": "..."},
  {"type": "loop", "beat": "dash|sam|muse|map", "slow": 1.0, "presenter": "..."},
  {"type": "card", "seconds": 8, "heading": "...", "bullets": ["..."], "note": "...", "image_prompt": "<muse-image prompt in the TBio palette, or omit>", "presenter": "..."},
  {"type": "results_stats", "seconds": 12, "heading": "...", "stats": [{"big": "20x", "line": "<at most 50 chars>", "sub": "<at most 70 chars>"}, {"big": "17x", ...}, {"big": "+1", ...}], "footnote": "<source line, at most 140 chars>", "presenter": "..."},
  {"type": "results_chart", "seconds": 10, "heading": "...", "line": "<at most 60 chars>", "sub": "<at most 90 chars>", "green_line": "<at most 100 chars>", "presenter": "..."},
  {"type": "end", "seconds": 5, "heading": "PhasePilot", "lines": ["...", "..."], "green_line": "...", "credits": ["...", "..."], "presenter": "..."}
], "style_notes": "one or two sentences on what you changed in the look and why"}
"""


def call(messages, max_tokens=60000, effort='medium'):
    body = dict(model=MODEL, messages=messages, max_tokens=max_tokens, temperature=0.6, reasoning_effort=effort)
    req = urllib.request.Request(BASE + '/chat/completions', data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + ENV['MUSE_API_KEY'], 'Content-Type': 'application/json'})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        j = json.load(r)
    msg = j['choices'][0]['message']['content']
    print(f'muse-wonder replied in {time.time() - t0:.0f} s, usage {j.get("usage")}', file=sys.stderr)
    return msg


def parse(text):
    m = re.search(r'\{.*\}', text, re.S)
    return json.loads(m.group(0))


def check(plan):
    total = 0.0
    for b in plan['beats']:
        if b['type'] == 'explainer':
            d = b['len'] * b.get('slow', 1.0)
        elif b['type'] == 'loop':
            d = {'dash': 6, 'sam': 11, 'muse': 12, 'map': 20}[b['beat']] * b.get('slow', 1.0)
        else:
            d = float(b['seconds'])
        b['_dur'] = round(d, 3)
        total += d
    return total


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default=str(HERE / 'muse/plan.json'))
    a = p.parse_args()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    messages = [{'role': 'user', 'content': BRIEF}]
    plan = None
    for attempt in range(3):
        text = call(messages)
        Path(a.out).with_suffix(f'.raw{attempt}.txt').write_text(text or '')
        try:
            plan = parse(text)
            total = check(plan)
        except Exception as e:
            messages += [{'role': 'assistant', 'content': text or ''}, {'role': 'user', 'content': f'That was not valid JSON ({e}). Reply with the JSON plan only.'}]
            continue
        print(f'attempt {attempt}: {len(plan["beats"])} beats, total {total:.1f} s', file=sys.stderr)
        if abs(total - 180.0) <= 1.5:
            break
        messages += [{'role': 'assistant', 'content': text},
                     {'role': 'user', 'content': f'Your beats sum to {total:.1f} s, not 180.0 s (explainer = len x slow; loop beats are '
                                                 f'dash 6 s, sam 11 s, muse 12 s, map 20 s times slow). Adjust and reply with the JSON only.'}]
    if plan is None:
        sys.exit('no valid plan from Muse Wonder; see the .raw*.txt replies')
    Path(a.out).write_text(json.dumps(plan, indent=1))
    print(json.dumps({k: v for k, v in plan.items() if k != 'beats'}, indent=1))
    for b in plan['beats']:
        print(f"{b['_dur']:6.1f}s  {b['type']:9s} {b.get('beat', '')} {b.get('heading', '')} | {b.get('presenter', '')[:90]}")
    print('total', round(sum(b['_dur'] for b in plan['beats']), 1))


if __name__ == '__main__':
    main()
