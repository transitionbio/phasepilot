"""PhasePilot 3-minute film, v2: the structure of phasepilot_final.mp4 with Will's DARK explainer as the base for his
content (more complete: formula line, "we can do better", photo tiles), re-styled to Transition Bio without touching the
animations: lightness inverted with hues kept (negate + hue 180), background pushed to white, scaled 90 % onto a white
page with the logo top-left. Will's notes folded in: results on two slides with the numbers revealed one at a time
(no wall-clock detail), linear scaling chart with large labels, and the multi-dimensional biology animation fading
into the application space before the end card.

    python build_final2.py --out phasepilot_final2.mp4
"""
import argparse
import tempfile
from pathlib import Path

from PIL import Image

from build_tbio import W, H, HERE, logo, title_card, run
from build_final import PHONE, TBIO, FADE, enc, seg_video, seg_still, seg_portrait, side_card, end_card, xfade_join
from build_muse import results_stats, results_chart

DARK = Path(__file__).resolve().parent / 'source/phasepilot-the-problem_dark.mp4'
SCALE = 0.88
VX, VY = int((W - W * SCALE) / 2), 125          # the inverted explainer sits here on the white page


def page_png(path):
    img = Image.new('RGB', (W, H), 'white')
    logo(img, 62, 26, 420)
    img.save(path)


def seg_dark(out, page, ss, src_len, slow=1.0, fades=(True, True)):
    """Will's dark explainer, lightness-inverted with hues kept, white background, on the logo page."""
    duration = src_len * slow
    vw, vh = int(W * SCALE) // 2 * 2, int(H * SCALE) // 2 * 2
    fc = (f'[1:v]setpts={slow:.4f}*PTS,negate,hue=h=180,colorlevels=rimax=0.90:gimax=0.93:bimax=0.93,'
          f'scale={vw}:{vh},fps=30[e];[0:v][e]overlay={VX}:{VY},format=yuv420p[v]')
    enc(out, ['-loop', '1', '-framerate', '30', '-i', str(page), '-ss', f'{ss:.3f}', '-t', f'{src_len:.3f}', '-i', str(DARK)],
        fc, duration, fades)
    return duration


MAP_W = 1360                                     # the map animation (1180x700) scaled to this width, left of a side panel


def map_card(path, heading, items, note):
    """White page, logo, heading, and a narrow light-blue panel on the right of the map area."""
    from PIL import ImageDraw
    from build_tbio import BLUE, GREEN, INK, MUTED, PANEL, font, wrap_text
    img = Image.new('RGB', (W, H), 'white')
    logo(img)
    d = ImageDraw.Draw(img)
    d.text((62, 168), heading, font=font(46, True), fill=BLUE)
    px, py = 62 + MAP_W + 30, 240
    d.rounded_rectangle([px, py, W - 60, 1040], radius=18, fill=PANEL)
    y = py + 40
    for b in items:
        d.ellipse([px + 26, y + 10, px + 40, y + 24], fill=GREEN)
        y = wrap_text(d, px + 56, y, b, font(24), INK, 28, 32) + 26
    wrap_text(d, px + 26, 930, note, font(18), MUTED, 40, 24)
    img.save(path)


def seg_map(out, card, anim, duration):
    """The map animation over the card, scaled to MAP_W at (62, 240); the last frame holds to the end."""
    enc(out, ['-loop', '1', '-framerate', '30', '-i', str(card), '-i', str(anim)],
        f'[1:v]scale={MAP_W}:-2,fps=30[m];[0:v][m]overlay=62:240:eof_action=repeat,format=yuv420p[v]', duration, (False, True))
    return duration


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default=str(HERE / 'phasepilot_final2.mp4'))
    a = p.parse_args()
    work = Path(tempfile.mkdtemp())
    page = work / 'page.png'
    page_png(page)
    parts, durs = [], []

    def add(name, fn, duration):
        out = work / f'{name}.mp4'
        fn(out)
        parts.append(out)
        durs.append(duration)

    # 1 title
    title = work / 'title.png'
    title_card(title, 'PhasePilot', 'Closed-loop phase mapping with PhaseScan and Muse')
    add('title', lambda o: seg_still(o, title, 4), 4)

    # 2 Will (dark base): condensates -> phase separation -> every protein has its own phase diagram (0-23 s)
    add('will1', lambda o: seg_dark(o, page, 0, 23, 1.1), 23 * 1.1)

    # 3-4 the rig, Will's phone footage
    c3 = work / 'rig1.png'
    side_card(c3, 'PhaseScan: the instrument',
              ['Beta3 microfluidic rig at Transition Bio',
               'Syringe pumps mix protein, RNA, crowder and buffer on a chip',
               'Every droplet is 100 picolitres and one experimental condition'],
              'Footage: Beta3, 4 November 2026')
    add('rig1', lambda o: seg_portrait(o, PHONE, 15, 9, c3), 9)
    c4 = work / 'rig2.png'
    side_card(c4, 'Droplets as experiments',
              ['Droplets are imaged in three fluorescence channels as they flow past the camera',
               'A CNN calls each droplet mixed or phase separated, live',
               'About a million times less protein per data point than plate-based labware'],
              'Footage: Beta3, 4 November 2026')
    add('rig2', lambda o: seg_portrait(o, PHONE, 30, 8, c4), 8)

    # 5 Will (dark base): droplet counter -> every new dimension (formula, "we can do better") -> handed to Muse
    #   -> SAM reads every droplet -> sampling goes where the information is (29-67.7 s, before the [X]/[Y] beat)
    add('will2', lambda o: seg_dark(o, page, 29, 38.7, 1.08), 38.7 * 1.08)

    # 6 today, live: the dashboard on the rig monitor
    c6 = work / 'live.png'
    side_card(c6, 'Today on the rig: the loop, live',
              ['G3BP1 / PolyA RNA / PEG on Beta3, 4 November 2026',
               'Muse chooses each setpoint from the live evidence and explains why',
               'SAM outlines every droplet; a result only counts when the image passes'],
              'Phone footage of the PhasePilot dashboard during the run')
    add('live', lambda o: seg_portrait(o, PHONE, 2, 6, c6, crop=(1080, 1500, 0, 60)), 6)

    # 7 our dashboard / SAM / Muse beats, then the dashboard with the map panel boxed (4 s)
    for name, ss, ln, slow, fades in (('dash', 3, 6, 1.1, (True, False)), ('sam', 9, 11, 0.85, (False, False)),
                                      ('muse', 20, 12, 1.0, (False, False)), ('map0', 32, 4, 1.0, (False, False))):
        add(name, lambda o, ss=ss, ln=ln, slow=slow, fades=fades: seg_video(o, TBIO, ss, ln, slow, fades), ln * slow)

    # 7b the real-time phase map, full width: the planner's GP map redrawn as each result lands (tbio/map_anim.mp4)
    c7 = work / 'rtmap.png'
    map_card(c7, 'The phase map, drawn in real time',
             ['Every result redraws the map and the predicted boundary',
              'Blue mixed, red phase separated, dashed line = boundary',
              'Faded = uncertain: that is where the planner samples next',
              'The run stops when the map stops changing'],
             'Replay run, G3BP1 / PolyA RNA / PEG, PEG slice fixed; one frame per decision, cross-faded')
    anim = HERE / 'tbio/map_anim.mp4'
    add('rtmap', lambda o: seg_map(o, c7, anim, 15.8), 15.8)

    # 8 results, two slides (Will): the numbers one at a time, then the linear chart
    stats = dict(heading='What PhasePilot changes',
                 stats=[dict(big='20x', line='less protein to map the phase boundary', sub='2.5 uL instead of 52 uL'),
                        dict(big='17x', line='less instrument run time', sub='pumps and camera busy 2.9 min instead of 51 min'),
                        dict(big='+1', line='variable in the same instrument time and protein', sub='at 10 levels per variable; +2 variables at 4 levels')],
                 footnote='3-variable replay (G3BP1 / TDP-43 / RNA), boundary accuracy at or above 0.997 vs the full scan.')
    subs = []
    for k in (1, 2, 3):
        c = work / f'stats{k}.png'
        results_stats(c, stats, k)
        o = work / f'stats{k}.mp4'
        seg_still(o, c, 10 / 3, (k == 1, k == 3))
        subs.append(o)
    lst = work / 'stats.txt'
    lst.write_text(''.join(f"file '{s}'\n" for s in subs))
    add('stats', lambda o: run(['-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', str(o)]), 10)
    c8 = work / 'chart.png'
    results_chart(c8, dict(heading='Every added variable', line='36 days vs 2 days at six variables',
                           sub='Legacy scan vs PhasePilot, instrument days',
                           green_line='A raster costs k^n conditions; the loop samples the boundary, ~k^(n-1). Each added variable costs the loop what the previous one cost the raster.'))
    add('chart', lambda o: seg_still(o, c8, 9), 9)

    # 9 Will (dark base): biology is high-dimensional fading into one closed loop, any parameter space (75-89.5 s)
    add('will3', lambda o: seg_dark(o, page, 75, 14.5, 1.05), 14.5 * 1.05)

    # 10 end card
    end = work / 'end.png'
    end_card(end)
    total_so_far = sum(durs)
    end_len = round(max(4.0, 180.0 - total_so_far), 3)
    add('end', lambda o: seg_still(o, end, end_len), end_len)

    total = xfade_join(parts, durs, a.out)
    print(f'wrote {a.out}  ({total:.1f} s, end card {end_len} s)  work {work}')


if __name__ == '__main__':
    main()
