"""Play the live worker's saved SAM frames (worker_out/sam_frames/frame_<n>.png + .json) as a video with a
status line (checked / rejected) under each frame.

    python render_sam_seq.py --run runs/<stamp> --out sam_seq.mp4 [--fps 2.5]
"""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FF = Path.home() / 'phasescan-closed-loop/.venv-gui/lib/python3.7/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux64-v4.2.2'
FONT = '/usr/share/fonts/truetype/msttcorefonts/Arial.ttf'


def main():
    a = argparse.ArgumentParser()
    a.add_argument('--run', required=True); a.add_argument('--out', required=True)
    a.add_argument('--fps', type=float, default=2.5); a.add_argument('--size', type=int, default=700)
    args = a.parse_args()
    frames = sorted((Path(args.run) / 'worker_out/sam_frames').glob('frame_*.png'))
    work = Path(tempfile.mkdtemp())
    f = ImageFont.truetype(FONT, 26)
    for i, png in enumerate(frames):
        meta = json.loads(png.with_suffix('.json').read_text())
        im = Image.open(png).convert('RGB').resize((args.size, args.size), Image.LANCZOS)
        canvas = Image.new('RGB', (args.size, args.size + 50), 'white')
        canvas.paste(im, (0, 0))
        d = ImageDraw.Draw(canvas)
        rej = meta['rejected'] / max(meta['checked'], 1)
        d.text((0, args.size + 12), f'frame {meta["frame"]}: SAM checked {meta["checked"]} droplets, '
               f'rejected {meta["rejected"]} ({rej:.0%})', font=f, fill=(207, 29, 16) if rej > 0.9 else (64, 64, 64))
        canvas.save(work / f'f_{i:04d}.png')
    subprocess.run([str(FF), '-y', '-loglevel', 'error', '-framerate', str(args.fps), '-i', str(work / 'f_%04d.png'),
                    '-vf', 'fps=30,format=yuv420p', '-c:v', 'libx264', '-preset', 'fast', args.out], check=True)
    print('wrote', args.out, len(frames), 'frames', len(frames) / args.fps, 's')


if __name__ == '__main__':
    main()
