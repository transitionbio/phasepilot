"""PhasePilot 3-minute demo for the Muse hackathon panel.

Order: TBio title; Will's explainer (condensates -> phase diagram); Will's phone footage of the Beta3 rig
framed in a TBio panel; Will's explainer (dimensionality -> Muse -> SAM -> sampling); the loop running live
today (phone footage of the dashboard); our dashboard/SAM/Muse/map beats (from phasepilot_tbio.mp4); the
results card; Will's closing (biology is high-dimensional, one closed loop); TBio end card. Every segment is
normalised to 1920x1080 @ 30 fps, silent, and joined with 0.6 s cross-fades.

    python build_final.py --out phasepilot_final.mp4
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from build_tbio import FF, W, H, BLUE, GREEN, INK, MUTED, PANEL, HERE, font, logo, wrap_text, title_card, results_card, run

DATA = Path(__file__).resolve().parent / 'source'
EXPLAINER = DATA / 'phasepilot-the-problem.mp4'      # light version, 1280x720 @ 15 fps
PHONE = DATA / 'live_rig_video.mp4'                   # portrait phone video: 0-14 s dashboard monitor, 14-44 s rig
TBIO = HERE / 'phasepilot_tbio.mp4'                   # our 64 s film: title 0-3, beats 3-52, results 52-64
FADE = 0.6


def enc(out, extra_inputs, fc, duration, fades=(True, True)):
    """Encode one segment; segments fade in from white and out to white so the concat reads as cross-fades
    (this ffmpeg, 4.2.2, has no xfade filter). fades=(in, out) switches either off for consecutive sub-segments."""
    f = ''
    if fades[0]:
        f += f',fade=t=in:st=0:d={FADE}:color=white'
    if fades[1]:
        f += f',fade=t=out:st={duration - FADE:.3f}:d={FADE}:color=white'
    fc = fc.replace('[v]', f + '[v]')
    run([*extra_inputs, '-filter_complex', fc, '-map', '[v]', '-t', f'{duration:.3f}', '-r', '30', '-an',
         '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', str(out)])


def seg_video(out, src, ss, src_len, slow=1.0, fades=(True, True)):
    """A 16:9 source, scaled to 1920x1080 and resampled to 30 fps; slow > 1 stretches it, < 1 speeds it up
    (no audio anywhere). Returns the segment duration."""
    duration = src_len * slow
    enc(out, ['-ss', f'{ss:.3f}', '-t', f'{src_len:.3f}', '-i', str(src)],
        f'[0:v]setpts={slow:.4f}*PTS,scale={W}:{H},fps=30,format=yuv420p[v]', duration, fades)
    return duration


def seg_still(out, card, duration, fades=(True, True)):
    enc(out, ['-loop', '1', '-framerate', '30', '-i', str(card)], '[0:v]format=yuv420p[v]', duration, fades)


def side_card(path, heading, items, note=''):
    """Transparent overlay: logo top-left, heading under it, TBio panel on the right. The video goes at x=120."""
    img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # logo and heading in a white band above the panel, on the right, clear of the full-height video on the left
    px = 1180
    d.rounded_rectangle([px, 36, W - 60, 232], radius=18, fill=(255, 255, 255, 225))
    logo(img, px + 30, 56, 400)
    d.text((px + 32, 160), heading, font=font(38, True), fill=BLUE)
    py = 262
    d.rounded_rectangle([px, py, W - 60, 1030], radius=18, fill=(*PANEL, 235))
    y = py + 60
    for b in items:
        d.ellipse([px + 38, y + 13, px + 56, y + 31], fill=GREEN)
        y = wrap_text(d, px + 88, y, b, font(31), INK, 30, 42) + 34
    if note:
        wrap_text(d, px + 34, 960, note, font(22), MUTED, 48, 28)
    img.save(path)


def seg_portrait(out, src, ss, duration, card, crop=None):
    """Portrait phone footage: blurred, darkened copy fills the frame; the clip itself is centred-left at full height;
    the TBio side card goes on top. crop=(w,h,x,y) in source pixels (after auto-rotation, 1080x1920)."""
    fg = f'crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]},' if crop else ''
    fc = (f'[0:v]split[a][b];'
          f'[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:2,'
          f'colorlevels=rimax=0.8:gimax=0.8:bimax=0.8[bg];'
          f'[b]{fg}scale=-2:{H - 100}[fgv];'
          f'[bg][fgv]overlay=140:50[m];'
          f'[m][1:v]overlay=0:0,fps=30,format=yuv420p[v]')
    enc(out, ['-ss', f'{ss:.3f}', '-i', str(src), '-loop', '1', '-framerate', '30', '-i', str(card)], fc, duration)


def results_card2(path):
    img = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(img)
    logo(img)
    d.text((62, 168), 'What PhasePilot changes', font=font(46, True), fill=BLUE)
    stats = [('20x', 'less protein to map the phase boundary', '2.5 uL instead of 52 uL'),
             ('17x', 'less instrument run time: 3 min instead of 51', 'pumps and camera run only the conditions that pin the boundary'),
             ('+1', 'more variable in the same instrument time and protein, at 10 levels per variable',
              '+2 variables at 4 levels per variable: a 17x saving buys log_k(17) extra dimensions, and that holds at every n')]
    y = 262
    for big, line, sub in stats:
        d.text((62, y), big, font=font(84, True), fill=BLUE)
        yy = wrap_text(d, 262, y + 14, line, font(28, True), INK, 36, 36)
        wrap_text(d, 262, yy + 4, sub, font(22), MUTED, 50, 28)
        y += 168
    wrap_text(d, 62, 835, 'Wall clock today is 23 min vs 51 min: each round waits 3 min for droplets to incubate on chip '
              'before the next decision, while the pumps idle. Keeping droplets flowing through that wait brings the '
              'wall clock down to the instrument time.', font(20), INK, 76, 26)
    wrap_text(d, 62, 945, '3-variable replay (G3BP1 / TDP-43 / RNA, 180 s incubation), boundary accuracy at or above 0.997 vs the full scan.',
              font(18), MUTED, 95, 24)
    d.text((62, 992), 'Biology is high n: protein, RNA, crowder, salt, pH, compound, temperature ...', font=font(24, True), fill=GREEN)
    chart = Image.open(HERE / 'tbio/scaling2.png').convert('RGB')
    cw = 960
    chart = chart.resize((cw, int(chart.height * cw / chart.width)), Image.LANCZOS)
    img.paste(chart, (W - 60 - cw, 250))
    img.save(path)


def end_card(path):
    bg = Image.open(HERE / 'tbio/title_bg.jpg').convert('RGB')
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1), Image.LANCZOS).crop((0, 0, W, H))
    d = ImageDraw.Draw(bg)
    logo(bg, 62, 56, 520)
    d.text((110, 440), 'PhasePilot', font=font(96, True), fill=INK)
    d.text((114, 570), 'One closed loop per protein:', font=font(36), fill=INK)
    d.text((114, 618), 'PhaseScan runs it, SAM checks it, Muse decides.', font=font(36), fill=INK)
    d.text((114, 710), 'Built for the Muse hackathon, November 2026', font=font(30, True), fill=GREEN)
    d.text((114, 770), 'PhaseScan Beta3  ·  Muse (muse-spark-1.3)  ·  Segment Anything ViT-B', font=font(26), fill=MUTED)
    d.text((114, 812), 'Bayesian planner  ·  Transition Bio, Cambridge', font=font(26), fill=MUTED)
    bg.save(path)


def xfade_join(parts, durs, out):
    concat = parts[0].parent / 'concat.txt'
    concat.write_text(''.join(f"file '{p}'\n" for p in parts))
    run(['-f', 'concat', '-safe', '0', '-i', str(concat), '-c', 'copy', '-movflags', '+faststart', str(out)])
    return sum(durs)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default=str(HERE / 'phasepilot_final.mp4'))
    a = p.parse_args()
    work = Path(tempfile.mkdtemp())
    parts, durs = [], []

    def add(name, fn, duration):
        out = work / f'{name}.mp4'
        fn(out)
        parts.append(out)
        durs.append(duration)

    SLOW1 = 1.25  # Will's intro beats: time to read each point and talk over it
    SLOW2 = 1.15

    # 1 title
    title = work / 'title.png'
    title_card(title, 'PhasePilot', 'Closed-loop phase mapping with PhaseScan and Muse')
    add('title', lambda o: seg_still(o, title, 4), 4)

    # 2 Will: condensates -> phase separation -> every protein has its own phase diagram
    add('will1', lambda o: seg_video(o, EXPLAINER, 0, 22.5, SLOW1), 22.5 * SLOW1)

    # 3-4 the instrument, Will's phone footage (rig exterior, door, pumps, stage)
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
    add('rig2', lambda o: seg_portrait(o, PHONE, 30, 9, c4), 9)

    # 5 Will: a million times less protein per data point -> every new dimension multiplies the work -> handed to Muse
    #   -> SAM reads every droplet -> sampling goes where the information is
    add('will2', lambda o: seg_video(o, EXPLAINER, 28.5, 36.9, SLOW2), 36.9 * SLOW2)   # ends before 'the result' beat

    # 6 today, live: the dashboard on the rig monitor
    c6 = work / 'live.png'
    side_card(c6, 'Today on the rig: the loop, live',
              ['G3BP1 / PolyA RNA / PEG on Beta3, 4 November 2026',
               'Muse chooses each setpoint from the live evidence and explains why',
               'SAM outlines every droplet; a result only counts when the image passes'],
              'Phone footage of the PhasePilot dashboard during the run')
    add('live', lambda o: seg_portrait(o, PHONE, 2, 7, c6, crop=(1080, 1500, 0, 60)), 7)

    # 7 our dashboard / SAM / Muse / map beats from phasepilot_tbio.mp4 (dash 3-9, SAM 9-20, Muse 20-32, map 32-52),
    #   each at its own pace, no white fades between them
    for name, ss, ln, slow, fades in (('dash', 3, 6, 1.1, (True, False)), ('sam', 9, 11, 0.85, (False, False)),
                                      ('muse', 20, 12, 1.0, (False, False)), ('map', 32, 20, 1.0, (False, True))):
        add(name, lambda o, ss=ss, ln=ln, slow=slow, fades=fades: seg_video(o, TBIO, ss, ln, slow, fades), ln * slow)

    # 8 results
    res = work / 'results.png'
    results_card2(res)
    add('results', lambda o: seg_still(o, res, 18.2), 18.2)

    # 9 Will: one closed loop, any parameter space
    add('will3', lambda o: seg_video(o, EXPLAINER, 79.5, 8, SLOW2), 8 * SLOW2)

    # 10 end card
    end = work / 'end.png'
    end_card(end)
    add('end', lambda o: seg_still(o, end, 5), 5)

    total = xfade_join(parts, durs, a.out)
    print(f'wrote {a.out}  ({total:.1f} s)  work {work}')


if __name__ == '__main__':
    main()
