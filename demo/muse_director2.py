"""Muse Wonder builds the whole PhasePilot film: Will's animated beats are remade as Transition Bio slides from a set
of diagram primitives, and every other beat (real footage, dashboard, results, title, end) is specified by Muse too.
The renderer (build_muse.py) executes the plan.

    python muse_director2.py --out muse/plan3.json
"""
import argparse
import json
import sys
from pathlib import Path

from muse_director import call, parse, check, HERE

BRIEF = """You are building a 3-minute demo film, slide by slide, for the judging panel of the Muse hackathon (Meta).
The film presents PhasePilot by Transition Bio (Cambridge, UK): a closed loop in which Muse (muse-spark-1.3) chooses the next
setpoint on a PhaseScan microfluidic rig, Segment Anything (SAM ViT-B) checks every droplet image, and a Bayesian planner keeps
the phase map. Presenters talk over the film live; there is no voice track. You write every slide: its heading, the lines that
appear on the left and WHEN they appear, which diagram animates on the right, and the timing. A renderer executes your plan
exactly, so write the final copy, not notes.

STYLE (every slide, strictly): plain white background, Transition Bio logo top-left, heading in blue #1366AB (Arial bold),
lines on the left in dark grey #404040 (styles: "big" 40 pt bold, "body" 30 pt, "green" 30 pt bold #008759 for the key
line, "muted" 24 pt grey #6E7276), one animated diagram on the right in the same palette. Real lab footage and the real
dashboard recording keep their own look inside a Transition Bio frame. Title and end cards sit on the blue-bubble background.

BEAT TYPES YOU CAN USE
1. "anim": an animated slide. Fields: seconds (4-14), heading (<= 34 chars), lines (1-4 items, each {"t": seconds after the
   slide starts, "text": <= 90 chars, "style": big|body|green|muted}; leave the last line 2 s on screen), diagram, diagram_params.
   Diagrams (what they animate over the slide):
     cell          a cell with condensates forming; diagram_params {"aggregate": true} adds an aggregate at the end
     demix         mixed molecules on the left separating into dense droplets on the right
     phase_diagram protein vs partner scatter, the boundary draws in; diagram_params {"compound": true} then raises the
                   boundary with arrows and the label "with compound"
     droplet       one droplet grows, "100 pL", then a counter runs up to ~1,000,000x less protein per data point
     kn_curve      conditions = k^n against variables mapped (1-6), with a practical-budget line and an out-of-reach band;
                   a counter reads "<conditions> at <n> variables"; diagram_params {"levels": 10}
     loop          the closed loop: Muse at the centre, four stations appearing in turn (Muse proposes conditions,
                   PhaseScan runs the droplets, SAM checks the images, Bayesian model updates), a dot running round
     sam           droplets under a scanning line; outlines turn green as SAM reads them, with a "segmented N" counter
     sampling      Bayesian rounds 1-4: points accumulate near the boundary and the uncertainty band narrows
     nodes         variables of biology appearing as linked nodes; diagram_params {"names": [...]} (default: protein, RNA,
                   binding partners, phosphorylation, pH, temperature, crowder, compound)
     applications  the closed loop at the centre, application boxes appearing round it (Phase separation marked
                   "demonstrated here", Formulation, Cell culture, Enzyme engineering, Assay design)
2. "phone": real portrait phone footage from the lab today, full height over a blurred background with a side panel:
   fields ss (source second), seconds (6-10), heading (<= 30 chars), bullets (<= 3, each <= 95 chars), note (<= 140).
   Source: 2-12 s the PhasePilot dashboard on the rig monitor during the live run; 15-44 s the Beta3 rig (15-24 exterior
   and door, 24-34 syringe pumps and chip stage close up, 34-44 wide shot). Pick ss so ss + seconds stays inside one range.
3. "loop": our real dashboard recording, four beats: "dash" 6 s (the dashboard with its four panels numbered: decisions,
   Muse reasoning, SAM QC, results and phase map), "sam" 11 s (SAM outlines on real droplet frames, green accepted, red
   rejected), "muse" 12 s (Muse's written reasoning for a decision, readable), "map" 20 s (the planner's phase map
   redrawing as results land, predicted boundary dashed). Field slow 0.8-1.2 scales the length. Use all four, in order.
4. "results_stats": seconds (10-13), heading, stats: exactly three {"big","line" (<= 50 chars, do not repeat the big
   number), "sub" (<= 70)}, revealed one at a time; footnote (<= 140).
5. "results_chart": seconds (8-11), heading, line (<= 60), sub (<= 90), green_line (<= 100). The chart is fixed: instrument
   days against variables mapped, legacy scan vs PhasePilot, 36 days vs 2 days at six variables, guides at 1 week and 1 month.
6. "title": seconds 4-5, heading, subtitle (<= 70). 7. "end": seconds 5-6, heading, lines (<= 2, each <= 80), green_line
   (<= 60), credits (<= 3, each <= 70).

CONTENT TO KEEP (the story, in Will's words where they matter; all numbers exact)
  - Condensates help organise the cell: the right molecules, in the right place, at the right time. When they misfire:
    cancer and neurodegeneration.
  - Condensates form by phase separation: proteins demix into dense liquid droplets, like oil in water.
  - Every protein has its own phase diagram. Phase behaviour is highly multidimensional. Map it to learn the rules of
    condensation, and to find drugs that act on it (with compound the boundary rises: less phase separation).
  - PhaseScan: experiments in microfluidic droplets on the Beta3 rig. Each drop = 100 picolitres = 1 experimental
    condition; ~1,000,000x less protein per data point than conventional labware. Droplets are imaged in three
    fluorescence channels and a CNN calls each one mixed or phase separated, live.
  - Every new dimension multiplies the work: k levels per n variables = k^n conditions (100,000 at 5 variables,
    1,000,000 at 6, for 10 levels). Time is proportional to t0 times k^n. Past four or five parameters a comprehensive
    scan becomes impossible, and that is for one protein.
  - So we handed the experiment to Muse: Muse proposes conditions, PhaseScan runs the droplets, SAM processes the images,
    the Bayesian model updates. One closed loop per protein. Muse can only choose among run / replicate / pause / finish;
    the instrument controller checks every setpoint.
  - SAM reads every droplet, live: each droplet is segmented and its condensates outlined, so each image becomes data for
    the next round; a result only counts when the image passes.
  - Sampling goes where the information is: the Bayesian model updates after every round and steers toward the boundary.
  - Live today: G3BP1 / PolyA RNA / PEG on Beta3, 4 November 2026; Muse chose each setpoint from the live evidence and
    explained why.
  - Results (3-variable replay, G3BP1 / TDP-43 / RNA, boundary accuracy >= 0.997 vs the full scan): 20x less protein
    (2.5 uL instead of 52 uL); 17x less instrument run time (2.9 min instead of 51 min); +1 variable in the same
    instrument time and protein at 10 levels per variable, +2 at 4 levels (a 17x saving buys log_k(17) extra dimensions
    at every n; a raster costs k^n, the loop samples the boundary, ~k^(n-1)). Do NOT mention wall clock, 23 min,
    incubation or idle pumps.
  - Biology is high-dimensional: protein, RNA, binding partners, phosphorylation, pH, temperature. One closed loop, any
    parameter space: PhaseScan with Muse is a template for automated experiments well beyond phase separation.

PACING RULES: total exactly 180.0 s; animated slides 6-12 s each with lines spaced so a presenter can read and speak
each one; no slide under 4 s; results_stats then results_chart together >= 20 s; the closing is a "nodes" slide fading
into an "applications" slide (or one applications slide) then the end card; include at least one phone beat of the rig
and one of the live dashboard, and all four loop beats; roughly 12-16 beats.

Reply with JSON only:
{"title": "...", "beats": [ ...beats in order, each with a one-sentence "presenter" line... ],
 "style_notes": "one or two sentences"}
"""


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default=str(HERE / 'muse/plan3.json'))
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
            plan = None
            continue
        print(f'attempt {attempt}: {len(plan["beats"])} beats, total {total:.1f} s', file=sys.stderr)
        if abs(total - 180.0) <= 1.0:
            break
        messages += [{'role': 'assistant', 'content': text},
                     {'role': 'user', 'content': f'Your beats sum to {total:.1f} s, not 180.0 s (loop beats are dash 6, sam 11, '
                                                 f'muse 12, map 20 s times slow). Adjust the seconds and reply with the JSON only.'}]
    if plan is None:
        sys.exit('no valid plan')
    Path(a.out).write_text(json.dumps(plan, indent=1))
    print(json.dumps({k: v for k, v in plan.items() if k != 'beats'}, indent=1))
    for b in plan['beats']:
        print(f"{b['_dur']:6.1f}s  {b['type']:13s} {b.get('beat', b.get('diagram', '')):13s} {b.get('heading', '')}")
    print('total', round(sum(b['_dur'] for b in plan['beats']), 1))


if __name__ == '__main__':
    main()
