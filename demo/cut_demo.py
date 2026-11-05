"""Cut the raw PhasePilot screen recording into beats, with optional title cards and captions.

An optional "prefilter" list in the edit JSON (ffmpeg video filters) is applied to every raw segment before
anything else, e.g. to crop off the recording's top banner.

Input: the raw recording (record_local.py, 2 fps), its start epoch time (printed as 'start <t>' in the record
log) and a JSON edit list:
    {"cards": {...}, "segments": [{"from": "<decision n>|<epoch>|<video s>", "to": ..., "speed": 1, "caption": "..."}]}
A segment's "from"/"to" may be a video offset in seconds, an epoch time, or "d<n>" for the time of decision n in
decisions.jsonl. Title cards are rendered as 1920x1080 PNGs (PIL) and held for a few seconds; captions are burnt
in at the bottom of each segment. Output: one MP4 (H.264, 30 fps).

    python cut_demo.py --raw recording.mp4 --start 1793750000.0 --decisions <run>/log/decisions.jsonl \
        --edit edit.json --out phasepilot_demo.mp4
"""
import argparse
import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path('/usr/share/fonts/truetype/dejavu')
W, H = 1920, 1080
FFMPEG = Path.home() / 'phasescan-closed-loop/.venv-gui/lib/python3.7/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux64-v4.2.2'


def font(size, bold=False):
    return ImageFont.truetype(str(FONT_DIR / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')), size)


def card(path, title, lines, footer, small=''):
    image = Image.new('RGB', (W, H), (18, 22, 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, W, 10], fill=(122, 31, 31))
    y = 180
    for part in textwrap.wrap(title, 36):
        draw.text((120, y), part, font=font(72, bold=True), fill=(245, 245, 245))
        y += 88
    y += 30
    for line in lines:
        for part in textwrap.wrap(line, 70) or ['']:
            draw.text((120, y), part, font=font(38), fill=(210, 214, 220))
            y += 54
        y += 14
    if small:
        for part in textwrap.wrap(small, 110):
            draw.text((120, y + 10), part, font=font(26), fill=(150, 155, 165))
            y += 36
    draw.text((120, H - 110), footer, font=font(28), fill=(200, 120, 120))
    image.save(path)


def resolve(value, start, decisions):
    if isinstance(value, str) and value.startswith('d'):
        n = int(value[1:])
        return next(r['time'] for r in decisions if r['decision'] == n) - start
    value = float(value)
    return value - start if value > 1e9 else value


def run(command):
    subprocess.run([str(FFMPEG), '-y', '-loglevel', 'error', *command], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--raw', required=True)
    p.add_argument('--start', type=float, required=True, help='epoch time of the recording\'s first frame')
    p.add_argument('--decisions', required=True)
    p.add_argument('--edit', required=True)
    p.add_argument('--out', required=True)
    args = p.parse_args()
    decisions = [json.loads(line) for line in open(args.decisions) if line.strip()]
    edit = json.loads(Path(args.edit).read_text())
    work = Path(tempfile.mkdtemp())
    parts = []
    caption_font = str(FONT_DIR / 'DejaVuSans-Bold.ttf')

    for index, item in enumerate(edit['sequence']):
        target = work / f'part_{index:02d}.mp4'
        if 'card' in item:
            c = edit['cards'][item['card']]
            png = work / f'card_{index:02d}.png'
            card(png, c['title'], c.get('lines', []), c.get('footer', ''), c.get('small', ''))
            run(['-loop', '1', '-framerate', '30', '-i', str(png), '-t', str(item.get('seconds', 6)),
                 '-vf', 'format=yuv420p', '-c:v', 'libx264', '-preset', 'fast', str(target)])
        else:
            t0 = resolve(item['from'], args.start, decisions)
            t1 = resolve(item['to'], args.start, decisions)
            speed = float(item.get('speed', 1))
            # optional per-edit filters applied to every raw segment first (e.g. crop off a burnt-in banner)
            filters = list(edit.get('prefilter', []))
            filters += ['fps=30', f'setpts=PTS/{speed}', 'format=yuv420p']  # fps first: setpts then fps does not shorten a 2 fps source
            if item.get('caption'):
                text = item['caption'].replace("'", "’").replace(':', '\\:')
                filters.append(f"drawtext=fontfile={caption_font}:text='{text}':fontsize=34:fontcolor=white:"
                               f"box=1:boxcolor=black@0.6:boxborderw=14:x=(w-text_w)/2:y=h-90")
            if speed != 1:
                filters.append(f"drawtext=fontfile={caption_font}:text='{speed:g}x':fontsize=30:fontcolor=white:"
                               f"box=1:boxcolor=black@0.5:boxborderw=10:x=w-140:y=40")
            run(['-ss', f'{t0:.2f}', '-to', f'{t1:.2f}', '-i', args.raw, '-vf', ','.join(filters),
                 '-c:v', 'libx264', '-preset', 'fast', '-an', str(target)])
        parts.append(target)

    concat = work / 'concat.txt'
    concat.write_text(''.join(f"file '{part}'\n" for part in parts))
    run(['-f', 'concat', '-safe', '0', '-i', str(concat), '-c', 'copy', args.out])
    print('wrote', args.out, 'from', len(parts), 'parts')


if __name__ == '__main__':
    main()
