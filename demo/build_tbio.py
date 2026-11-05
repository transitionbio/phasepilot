"""PhasePilot film in the Transition Bio template (~60 s): title; the real dashboard with its panels numbered;
SAM (the worker's saved frames played as video); Muse (dashboard with the panel highlighted, then the panel
readable); the loop (dashboard, then the planner's phase maps animated through the run); results.

    python build_tbio.py --raw recording/phasepilot_replay_261104_0949.mp4 --run runs/261104_0949 --out phasepilot_tbio.mp4
Needs tbio/map_anim.mp4 (render_map_anim.py) and tbio/sam_seq.mp4 (render_sam_seq.py) from the same run.
"""
import argparse
import os
import shutil
import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FF = Path(os.environ.get('FFMPEG', shutil.which('ffmpeg') or 'ffmpeg'))
W, H = 1920, 1080
BLUE, GREEN, ORANGE, RED = (19, 102, 171), (0, 135, 89), (239, 142, 0), (207, 29, 16)
INK, MUTED, PANEL = (64, 64, 64), (110, 114, 118), (219, 239, 249)
FONTS = Path('/usr/share/fonts/truetype/msttcorefonts')
ARIAL, ARIAL_B = FONTS / 'Arial.ttf', FONTS / 'Arial_Bold.ttf'
# panels in the 1920x1080 dashboard recording (PhasePilot tab)
DECISIONS = (24, 115, 922, 252)
MUSE = (972, 115, 924, 242)
SAM = (970, 404, 930, 640)
RESULTS = (24, 404, 924, 640)
DASH_W = 1200  # the whole dashboard, scaled to this width on the left of a beat


def font(size, bold=False):
    return ImageFont.truetype(str(ARIAL_B if bold else ARIAL), size)


def logo(img, x=62, y=56, w=470):
    lg = Image.open(HERE / 'tbio/logo.png').convert('RGBA')
    lg = lg.resize((w, int(lg.height * w / lg.width)), Image.LANCZOS)
    img.paste(lg, (x, y), lg)


def wrap_text(draw, x, y, text, f, fill, width_chars, line_h):
    for line in textwrap.wrap(text, width_chars):
        draw.text((x, y), line, font=f, fill=fill)
        y += line_h
    return y


def title_card(path, title, subtitle):
    bg = Image.open(HERE / 'tbio/title_bg.jpg').convert('RGB')
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1), Image.LANCZOS).crop((0, 0, W, H))
    d = ImageDraw.Draw(bg)
    logo(bg, 62, 56, 520)
    d.text((110, 560), title, font=font(96, True), fill=INK)
    d.text((114, 690), subtitle, font=font(40), fill=INK)
    bg.save(path)


def beat_card(path, heading, panel_title, items, note='', numbered=False):
    img = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(img)
    logo(img)
    d.text((62, 168), heading, font=font(46, True), fill=BLUE)
    px, py = 1290, 250
    d.rounded_rectangle([px, py, W - 60, 1000], radius=18, fill=PANEL)
    d.text((px + 34, py + 30), panel_title, font=font(30, True), fill=INK)
    y = py + 110
    for i, b in enumerate(items, 1):
        if numbered:
            d.rounded_rectangle([px + 32, y - 2, px + 72, y + 38], radius=8, fill=ORANGE)
            d.text((px + 44, y + 2), str(i), font=font(26, True), fill='white')
        else:
            d.ellipse([px + 38, y + 11, px + 54, y + 27], fill=GREEN)
        y = wrap_text(d, px + 88, y, b, font(28), INK, 30, 38) + 30
    if note:
        wrap_text(d, px + 34, 880, note, font(21), MUTED, 46, 28)
    img.save(path)


def results_card(path):
    img = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(img)
    logo(img)
    d.text((62, 168), 'What PhasePilot changes', font=font(46, True), fill=BLUE)
    stats = [('20x', 'less protein to map the phase boundary'),
             ('2x', 'faster at 180 s incubation (~10x with a 30 s protocol, projected)'),
             ('+1', 'variable mapped in the time of a legacy scan')]
    y = 262
    for big, small in stats:
        d.text((62, y), big, font=font(84, True), fill=BLUE)
        wrap_text(d, 262, y + 22, small, font(27), INK, 32, 36)
        y += 150
    wrap_text(d, 62, 730, '3-variable replay (G3BP1 / TDP-43 / RNA, 180 s incubation), boundary accuracy at or '
              'above 0.99 vs the full scan.', font(20), MUTED, 62, 27)
    wrap_text(d, 62, 800, 'A raster costs k^n conditions for n variables at k levels. The loop samples near the '
              'boundary, a surface of n-1 dimensions: ~k^(n-1). Each added variable costs the loop what the '
              'previous one cost the raster.', font(21), INK, 60, 28)
    d.text((62, 960), 'Biology is high n: protein, RNA, crowder, salt, pH, compound, temperature ...', font=font(24, True), fill=GREEN)
    chart = Image.open(HERE / 'tbio/scaling.png').convert('RGB')
    cw = 1000
    chart = chart.resize((cw, int(chart.height * cw / chart.width)), Image.LANCZOS)
    img.paste(chart, (W - 60 - cw, 262))
    img.save(path)


def run(cmd):
    subprocess.run([str(FF), '-y', '-loglevel', 'error', *cmd], check=True)


def render_beat(out, card, layers, duration):
    """layers: dicts with src (video), ss (s into it), crop (x,y,w,h or None), x, y, w (dest), boxes
    [(x,y,w,h,label)] drawn in dest coordinates after the overlay. Still frames hold when a source ends."""
    cmd = ['-loop', '1', '-framerate', '30', '-i', str(card)]
    for L in layers:
        cmd += ['-ss', f'{L["ss"]:.2f}', '-i', str(L['src'])]
    fc, prev = [], '[0:v]'
    for i, L in enumerate(layers, 1):
        crop = f'crop={L["crop"][2]}:{L["crop"][3]}:{L["crop"][0]}:{L["crop"][1]},' if L.get('crop') else ''
        fc.append(f'[{i}:v]{crop}scale={L["w"]}:-2,fps=30[c{i}]')
        fc.append(f'{prev}[c{i}]overlay={L["x"]}:{L["y"]}:eof_action=repeat[o{i}]')
        prev = f'[o{i}]'
    extra = []
    for L in layers:
        for (bx, by, bw, bh, label) in L.get('boxes', []):
            extra.append(f'drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=0xEF8E00@1:t=5')
            extra.append(f"drawtext=fontfile={ARIAL_B}:text='{label}':fontsize=34:fontcolor=white:box=1:"
                         f"boxcolor=0xEF8E00@1:boxborderw=8:x={bx + bw - 10}-tw:y={by + 8}")
    fc.append(f'{prev}{",".join(extra) + "," if extra else ""}format=yuv420p[v]')
    run(cmd + ['-filter_complex', ';'.join(fc), '-map', '[v]', '-t', str(duration), '-c:v', 'libx264',
               '-preset', 'fast', str(out)])


def dash_layer(raw, ss, highlight=None, number=None):
    """The whole dashboard scaled to DASH_W at (62, 250), optionally with one or more panels boxed."""
    s = DASH_W / W
    boxes = []
    for (p, label) in (highlight or []):
        boxes.append((int(62 + p[0] * s), int(250 + p[1] * s), int(p[2] * s), int(p[3] * s), label))
    return dict(src=raw, ss=ss, crop=None, x=62, y=250, w=DASH_W, boxes=boxes)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--raw', required=True)
    p.add_argument('--run', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    start = float(Path(a.raw + '.start').read_text())
    dec = [json.loads(l) for l in open(Path(a.run) / 'log/decisions.jsonl') if l.strip()]
    t = {d['decision']: d['time'] - start for d in dec}
    work = Path(tempfile.mkdtemp())
    parts = []

    def still(name, card_fn, seconds):
        card = work / f'{name}.png'
        card_fn(card)
        out = work / f'{name}.mp4'
        run(['-loop', '1', '-framerate', '30', '-i', str(card), '-t', str(seconds), '-vf', 'format=yuv420p',
             '-c:v', 'libx264', '-preset', 'fast', str(out)])
        parts.append(out)

    def beat(name, card_fn, layers, seconds):
        card = work / f'{name}.png'
        card_fn(card)
        out = work / f'{name}.mp4'
        render_beat(out, card, layers, seconds)
        parts.append(out)

    # 1 title
    still('title', lambda c: title_card(c, 'PhasePilot', 'A self-driving loop for PhaseScan: SAM checks, Muse decides, the map updates'), 3)

    # 2 the dashboard, panels numbered (6 s)
    beat('dash', lambda c: beat_card(c, 'The PhasePilot dashboard', 'Everything the loop does, live',
                                     ['Every decision, and who made it', 'Muse\'s reasoning for the selected decision',
                                      'SAM droplet quality control', 'Results and the phase map'], numbered=True),
         [dash_layer(a.raw, t[6] + 2, [(DECISIONS, '1'), (MUSE, '2'), (SAM, '3'), (RESULTS, '4')])], 6)

    # 3 SAM (11 s): the worker's saved frames played as video
    beat('sam', lambda c: beat_card(c, 'SAM: droplet quality control', 'Segment Anything (Meta, ViT-B)',
                                    ['Outlines every droplet the detector finds',
                                     'Rejects partial or malformed droplets',
                                     'Empty channel: rejects all, the loop pauses',
                                     'Does not classify phase separation'],
                                    'Green = accepted, red = rejected. Frames from the run in order; the empty channel is an injected fault'),
         [dict(src=HERE / 'tbio/sam_seq.mp4', ss=0, crop=None, x=62, y=250, w=700)], 11)

    # 4 Muse (12 s): dashboard with the panel boxed, then the panel readable
    muse_card = lambda c: beat_card(c, 'Muse: reads the evidence and decides', 'Muse (Meta, muse-spark-1.3)',
                                    ['Reads results, image QC, budget and the planner\'s candidates',
                                     'Picks one action: run, replicate, pause or finish',
                                     'Explains every decision, logged and shown live'],
                                    'The controller still checks every setpoint and enforces the protein reserve')
    beat('muse1', muse_card, [dash_layer(a.raw, t[6] + 1.5, [(MUSE, 'Muse')])], 4)
    beat('muse2', muse_card, [dict(src=a.raw, ss=t[6] + 1.5, crop=MUSE, x=62, y=250, w=1180),
                              dict(src=a.raw, ss=t[6] + 1.5, crop=DECISIONS, x=62, y=575, w=1180)], 8)

    # 5 the loop (dashboard 4 s, then the planner's maps animated through the run)
    loop_card = lambda c: beat_card(c, 'The loop closes', 'Planner + instrument + live analysis',
                                    ['The planner ranks conditions by how likely the map is wrong there',
                                     'The setpoint runs; droplets are imaged and classified',
                                     'Each result redraws the map and the predicted boundary',
                                     'Stops when the map stops changing or the budget is spent'],
                                    'Blue = mixed, red = phase separated, dashed = predicted boundary, faded = uncertain')
    beat('loop1', loop_card, [dash_layer(a.raw, t[13] + 1, [(RESULTS, 'Phase map')])], 4)
    anim_len = float(subprocess.run([str(FF).replace('ffmpeg-linux64-v4.2.2', 'ffmpeg-linux64-v4.2.2'), '-i', str(HERE / 'tbio/map_anim.mp4')],
                                    capture_output=True, text=True).stderr.split('Duration: ')[1].split(',')[0].split(':')[-1])
    beat('loop2', loop_card, [dict(src=HERE / 'tbio/map_anim.mp4', ss=0, crop=None, x=62, y=250, w=1180)], round(anim_len) + 1)

    # 6 results
    still('results', results_card, 12)

    concat = work / 'concat.txt'
    concat.write_text(''.join(f"file '{p_}'\n" for p_ in parts))
    run(['-f', 'concat', '-safe', '0', '-i', str(concat), '-c', 'copy', a.out])
    print('wrote', a.out, 'cards in', work)


if __name__ == '__main__':
    main()
