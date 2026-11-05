"""PhasePilot film conformed to the recorded voiceover (OBS take), with the presenter in a small box during the
introduction and again from "that's PhasePilot" to the end.

Each narration block was located in the take with vosk word timings (anchors below, in seconds of the take). Every
beat of phasepilot_final2 is retimed to start when its block starts: animations play at up to 1.3x slower and then
hold their last frame; the phone footage simply runs longer; stills hold. The take's audio is muxed in untouched.

    python build_voiced.py --take "<obs mp4>" --out phasepilot_voiced.mp4
"""
import argparse
import tempfile
from pathlib import Path

from build_tbio import W, H, HERE, title_card, run
from build_final import PHONE, TBIO, FADE, seg_still, side_card, end_card
from build_final2 import DARK, SCALE, VX, VY, page_png, map_card, MAP_W
from build_muse import results_stats, results_chart

# start of each narration block in the take (s); 'end' = "thank you", 'pip_back' = "and that's PhasePilot"
A = dict(intro=0.0, cell=12.87, oil=27.60, map=37.05, rig=48.00, droplets=59.64, million=72.36, scan=80.73,
         muse_loop=96.75, readout=108.60, boundary=117.84, live=126.36, dashboard=140.28, sam=148.02,
         muse_decides=158.76, map_panel=173.19, map_rt=178.68, result=191.16, chart=205.80, biology=219.15,
         loop=228.33, pip_back=237.60, end=239.46, tail=241.50)
ORDER = ['intro', 'cell', 'oil', 'map', 'rig', 'droplets', 'million', 'scan', 'muse_loop', 'readout', 'boundary', 'live',
         'dashboard', 'sam', 'muse_decides', 'map_panel', 'map_rt', 'result', 'chart', 'biology', 'loop', 'pip_back']
SLOW_MAX = 1.3
INV = 'negate,hue=h=180,colorlevels=rimax=0.90:gimax=0.93:bimax=0.93'


XF = 0.5   # cross-dissolve length between beats


def fades(duration, first, last):
    """Segments carry no white fades any more: the joins are cross-dissolves made in crossfade()."""
    return ''


def crossfade(a, la, b, out, d=XF):
    """d seconds that replace the first d seconds of b: a's last frame held, with b's opening dissolving in over it.
    The timeline is unchanged, so every cue stays on its narration line."""
    run(['-ss', f'{la - 0.1:.3f}', '-t', '0.1', '-i', str(a), '-t', f'{d:.3f}', '-i', str(b), '-filter_complex',
         f'[0:v]tpad=stop_mode=clone:stop_duration=2[a0];[1:v]format=yuva420p,fade=t=in:st=0:d={d:.3f}:alpha=1[b];'
         f'[a0][b]overlay=0:0:shortest=1,format=yuv420p[v]',
         '-map', '[v]', '-t', f'{d:.3f}', '-r', '30', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', str(out)])


def encode(out, inputs, fc, duration):
    run([*inputs, '-filter_complex', fc, '-map', '[v]', '-t', f'{duration:.3f}', '-r', '30', '-an',
         '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', str(out)])


def fit_dark(out, page, ss, src_len, needed):
    slow = min(SLOW_MAX, needed / src_len)
    play = src_len * slow
    vw, vh = int(W * SCALE) // 2 * 2, int(H * SCALE) // 2 * 2
    fc = (f'[1:v]setpts={slow:.4f}*PTS,{INV},scale={vw}:{vh},fps=30,tpad=stop_mode=clone:stop_duration={max(0, needed - play) + 1:.3f}[e];'
          f'[0:v][e]overlay={VX}:{VY}{fades(needed, True, True)},format=yuv420p[v]')
    encode(out, ['-loop', '1', '-framerate', '30', '-i', str(page), '-ss', f'{ss:.3f}', '-t', f'{src_len:.3f}', '-i', str(DARK)], fc, needed)


def fit_video(out, src, ss, src_len, needed, slow_max=SLOW_MAX):
    slow = min(slow_max, needed / src_len)
    play = src_len * slow
    fc = (f'[0:v]setpts={slow:.4f}*PTS,scale={W}:{H},fps=30,tpad=stop_mode=clone:stop_duration={max(0, needed - play) + 1:.3f}'
          f'{fades(needed, True, True)},format=yuv420p[v]')
    encode(out, ['-ss', f'{ss:.3f}', '-t', f'{src_len:.3f}', '-i', str(src)], fc, needed)


def fit_portrait(out, src, ss, needed, card, crop=None, max_end=None):
    """Portrait phone footage as in build_final.seg_portrait, running for 'needed' seconds (freezing if the source
    range would run out)."""
    src_len = needed if max_end is None else min(needed, max_end - ss)
    fg = f'crop={crop[0]}:{crop[1]}:{crop[2]}:{crop[3]},' if crop else ''
    fc = (f'[0:v]split[a][b];'
          f'[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=40:2,colorlevels=rimax=0.8:gimax=0.8:bimax=0.8[bg];'
          f'[b]{fg}scale=-2:{H - 100}[fgv];[bg][fgv]overlay=140:50[m];'
          f'[m][1:v]overlay=0:0,fps=30,tpad=stop_mode=clone:stop_duration={max(0, needed - src_len) + 1:.3f}'
          f'{fades(needed, True, True)},format=yuv420p[v]')
    encode(out, ['-ss', f'{ss:.3f}', '-t', f'{src_len:.3f}', '-i', str(src), '-loop', '1', '-framerate', '30', '-i', str(card)], fc, needed)


def fit_map(out, card, anim, needed, anim_len=14.8):
    speed = min(1.0, needed / anim_len)       # faster if the narration is shorter than the animation
    fc = (f'[1:v]setpts={speed:.4f}*PTS,scale={MAP_W}:-2,fps=30,tpad=stop_mode=clone:stop_duration={needed + 1:.3f}[m];'
          f'[0:v][m]overlay=62:240{fades(needed, True, True)},format=yuv420p[v]')
    encode(out, ['-loop', '1', '-framerate', '30', '-i', str(card), '-i', str(anim)], fc, needed)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--take', required=True)
    p.add_argument('--out', default=str(HERE / 'phasepilot_voiced.mp4'))
    p.add_argument('--anchors', help='JSON of block start times in the take (default: the table in this file)')
    p.add_argument('--music', help='optional music bed (mp3/wav), looped, ducked under the voice')
    p.add_argument('--music_db', type=float, default=-20.0, help='music level in dB before ducking')
    p.add_argument('--music_credit', help='credit line drawn on the end card (CC BY tracks need it)')
    a = p.parse_args()
    if a.anchors:
        import json
        A.update(json.load(open(a.anchors)))
    work = Path(tempfile.mkdtemp())
    page = work / 'page.png'
    page_png(page)
    need = {k: A[ORDER[i + 1]] - A[k] for i, k in enumerate(ORDER[:-1])}
    parts = []

    def seg(name, fn):
        out = work / f'{ORDER.index(name):02d}_{name}.mp4'
        fn(out, need[name])
        parts.append((out, need[name]))
        print(f'{A[name]:7.2f}s  {name:13s} {need[name]:5.1f} s')

    title = work / 'title.png'
    title_card(title, 'PhasePilot', 'Closed-loop phase mapping with PhaseScan and Muse')
    seg('intro', lambda o, d: seg_still(o, title, d))
    # dark-explainer slices stop 0.25 s before the next beat so a frozen frame never shows the following slide
    seg('cell', lambda o, d: fit_dark(o, page, 0, 6.75, d))
    seg('oil', lambda o, d: fit_dark(o, page, 7, 6.75, d))
    seg('map', lambda o, d: fit_dark(o, page, 14, 8.75, d))
    c = work / 'rig1.png'
    side_card(c, 'PhaseScan: the instrument',
              ['Beta3 microfluidic rig at Transition Bio', 'Syringe pumps mix protein, RNA, crowder and buffer on a chip',
               'Every droplet is 100 picolitres and one experimental condition'], 'Footage: Beta3, 4 November 2026')
    seg('rig', lambda o, d: fit_portrait(o, PHONE, 15, d, c, max_end=29.5))
    c2 = work / 'rig2.png'
    side_card(c2, 'Droplets as experiments',
              ['Droplets are imaged in three fluorescence channels as they flow past the camera',
               'A CNN calls each droplet mixed or phase separated, live',
               'About a million times less protein per data point than plate-based labware'], 'Footage: Beta3, 4 November 2026')
    seg('droplets', lambda o, d: fit_portrait(o, PHONE, 30, d, c2, max_end=44))
    seg('million', lambda o, d: fit_dark(o, page, 29, 3.5, d))
    seg('scan', lambda o, d: fit_dark(o, page, 33, 11.75, d))
    seg('muse_loop', lambda o, d: fit_dark(o, page, 45, 7.75, d))
    seg('readout', lambda o, d: fit_dark(o, page, 53, 6.75, d))
    seg('boundary', lambda o, d: fit_dark(o, page, 60, 7.4, d))
    c6 = work / 'live.png'
    side_card(c6, 'Today on the rig: the loop, live',
              ['G3BP1 / PolyA RNA / PEG on Beta3, 4 November 2026', 'Muse chooses each setpoint from the live evidence and explains why',
               'SAM outlines every droplet; a result only counts when the image passes'], 'Phone footage of the PhasePilot dashboard during the run')
    seg('live', lambda o, d: fit_portrait(o, PHONE, 2, d, c6, crop=(1080, 1500, 0, 60), max_end=14))
    seg('dashboard', lambda o, d: fit_video(o, TBIO, 3, 6, d))
    seg('sam', lambda o, d: fit_video(o, TBIO, 9, 11, d))
    seg('muse_decides', lambda o, d: fit_video(o, TBIO, 20, 12, d))
    seg('map_panel', lambda o, d: fit_video(o, TBIO, 32, 4, d))
    c7 = work / 'rtmap.png'
    map_card(c7, 'The phase map, drawn in real time',
             ['Every result redraws the map and the predicted boundary', 'Blue mixed, red phase separated, dashed line = boundary',
              'Faded = uncertain: that is where the planner samples next', 'The run stops when the map stops changing'],
             'Replay run, G3BP1 / PolyA RNA / PEG, PEG slice fixed; one frame per decision, cross-faded')
    seg('map_rt', lambda o, d: fit_map(o, c7, HERE / 'tbio/map_anim.mp4', d))

    stats = dict(heading='What PhasePilot changes',
                 stats=[dict(big='20x', line='less protein to map the phase boundary', sub='2.5 uL instead of 52 uL'),
                        dict(big='17x', line='less instrument run time', sub='pumps and camera busy 2.9 min instead of 51 min'),
                        dict(big='+1', line='variable in the same instrument time and protein', sub='at 10 levels per variable; +2 variables at 4 levels')],
                 footnote='3-variable replay (G3BP1 / TDP-43 / RNA), boundary accuracy at or above 0.997 vs the full scan.')

    def stats_fn(o, d):
        subs = []
        for k in (1, 2, 3):
            cc = work / f'stats{k}.png'
            results_stats(cc, stats, k)
            oo = work / f'stats{k}.mp4'
            seg_still(oo, cc, d / 3, (False, False))
            subs.append(oo)
        lst = work / 'stats.txt'
        lst.write_text(''.join(f"file '{s}'\n" for s in subs))
        run(['-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', str(o)])
    seg('result', stats_fn)
    c8 = work / 'chart.png'
    results_chart(c8, dict(heading='Every added variable', line='36 days vs 2 days at six variables',
                           sub='Legacy scan vs PhasePilot, instrument days',
                           green_line='A raster costs k^n conditions; the loop samples the boundary, ~k^(n-1). Each added variable costs the loop what the previous one cost the raster.'))
    seg('chart', lambda o, d: seg_still(o, c8, d))
    seg('biology', lambda o, d: fit_dark(o, page, 75, 5.75, d))
    seg('loop', lambda o, d: fit_dark(o, page, 81, 8.5, d))
    end = work / 'end.png'
    end_card(end)
    # the end card runs from the end of the 'loop' block to the tail
    out_end = work / f'{len(ORDER):02d}_end.mp4'
    end_len = A['tail'] - (A['loop'] + need['loop'])
    seg_still(out_end, end, end_len, (False, False))
    parts.append((out_end, end_len))
    print(f'{A["loop"] + need["loop"]:7.2f}s  {"end card":13s} {end_len:5.1f} s')

    # cross-dissolve every join inside the first XF seconds of the incoming segment: segment i in full, then the
    # dissolve clip, then segment i+1 from XF onwards; total time unchanged
    lines = []
    for i, (path, ln) in enumerate(parts):
        inp = XF if i > 0 else 0.0
        lines.append(f"file '{path}'\ninpoint {inp:.3f}\noutpoint {ln:.3f}\n")
        if i < len(parts) - 1:
            xf = work / f'xf_{i:02d}.mp4'
            crossfade(path, ln, parts[i + 1][0], xf)
            lines.append(f"file '{xf}'\n")
    concat = work / 'concat.txt'
    concat.write_text(''.join(lines))
    silent = work / 'silent.mp4'
    total = A['tail']
    run(['-f', 'concat', '-safe', '0', '-i', str(concat), '-vf',
         f'fps=30,fade=t=in:st=0:d=0.6:color=white,fade=t=out:st={total - 0.8:.3f}:d=0.8:color=white,format=yuv420p',
         '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-an', str(silent)])

    # presenter box bottom-right during the intro and from "that's PhasePilot" to the end; the take's audio throughout;
    # optional music bed ducked under the voice, swelling on the title and end cards
    pw, ph, bw = 420, 236, 8
    x, y = W - pw - 60 - bw, H - ph - 60 - bw
    fc = (f'[1:v]scale={pw}:{ph},pad={pw + 2 * bw}:{ph + 2 * bw}:{bw}:{bw}:white,fps=30[pip];'
          f"[0:v][pip]overlay={x}:{y}:enable='between(t,0,{A['cell'] - 0.3:.2f})+between(t,{A['pip_back']:.2f},{total + 1:.2f})',format=yuv420p[v]")
    if a.music and a.music_credit:
        from build_tbio import ARIAL
        credit = a.music_credit.replace("'", '').replace(':', '\\:')
        fc = fc.replace(',format=yuv420p[v]',
                        f",drawtext=fontfile={ARIAL}:text='{credit}':fontsize=22:fontcolor=0x6E7276:x=114:y=1010:"
                        f"enable='between(t,{A['pip_back']:.2f},{total + 1:.2f})',format=yuv420p[v]")
    inputs = ['-i', str(silent), '-i', a.take]
    if a.music:
        inputs += ['-stream_loop', '-1', '-i', a.music]
        fc += (f';[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={a.music_db}dB,'
               f'afade=t=in:st=0:d=2,afade=t=out:st={total - 3:.2f}:d=3[m];'
               f'[1:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit[voice][sc];'
               f'[m][sc]sidechaincompress=threshold=0.02:ratio=4:attack=50:release=800:makeup=1[duck];'
               f'[voice][duck]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]')
        amap = ['-map', '[a]']
    else:
        amap = ['-map', '1:a']
    run([*inputs, '-filter_complex', fc, '-map', '[v]', *amap, '-t', f'{total:.3f}',
         '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
         '-movflags', '+faststart', str(a.out)])
    print('wrote', a.out, f'({total:.1f} s)', 'work', work)


if __name__ == '__main__':
    main()
