"""Tighten the OBS take: drop the awkward pause after "Hi", cap every pause longer than 0.5 s to 0.35 s, then speed
the whole thing up slightly (atempo, pitch preserved) so the narration lands at the target length. Writes the edited
take (video + audio) and the narration anchors remapped into the edited timeline for build_voiced.py.

    python edit_take.py --take "<obs mp4>" --words take_words.json --out take_edit.mp4 --anchors anchors_edit.json --target 179
"""
import argparse
import json
import subprocess
from pathlib import Path

from build_tbio import FF
from build_voiced import A as ANCHORS

GAP_MIN, GAP_KEEP = 0.5, 0.35


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--take', required=True)
    p.add_argument('--words', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--anchors', required=True)
    p.add_argument('--target', type=float, default=179.0, help='narration length in s after the speed-up (end of last word)')
    p.add_argument('--tail', type=float, default=1.3, help='seconds kept after the last word')
    a = p.parse_args()
    w = json.load(open(a.words))
    cuts = [(0.3, 3.0)]      # "Hi" ... long pause ... "I'm": drop the pause
    for i in range(1, len(w)):
        gap = w[i]['start'] - w[i - 1]['end']
        if gap > GAP_MIN and w[i - 1]['end'] > 3.0:
            half = (gap - GAP_KEEP) / 2
            cuts.append((w[i - 1]['end'] + GAP_KEEP / 2 + 0, w[i]['start'] - GAP_KEEP / 2))
            cuts[-1] = (w[i - 1]['end'] + 0.175, w[i]['start'] - 0.175)
    cuts.sort()
    last_word_end = w[-1]['end']
    src_end = last_word_end + a.tail
    keep, t = [], 0.0
    for c0, c1 in cuts:
        if c0 > t:
            keep.append((t, c0))
        t = c1
    keep.append((t, src_end))
    kept = sum(b - a_ for a_, b in keep)
    removed_before = lambda x: sum(min(c1, x) - c0 for c0, c1 in cuts if c0 < x)
    tempo = (last_word_end - removed_before(last_word_end)) / a.target
    tempo = max(1.0, round(tempo, 4))
    print(f'{len(cuts)} cuts removing {src_end - kept:.1f} s; kept {kept:.1f} s; tempo {tempo:.3f} -> {kept / tempo:.1f} s')

    # ffmpeg: trim/concat the kept ranges for video and audio, then speed up
    fc = []
    for i, (s, e) in enumerate(keep):
        fc.append(f'[0:v]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS[v{i}]')
        fc.append(f'[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS[a{i}]')
    fc.append(''.join(f'[v{i}][a{i}]' for i in range(len(keep))) + f'concat=n={len(keep)}:v=1:a=1[vc][ac]')
    fc.append(f'[vc]setpts=PTS/{tempo:.4f},fps=30[v]')
    fc.append(f'[ac]atempo={tempo:.4f}[a]')
    subprocess.run([str(FF), '-y', '-loglevel', 'error', '-i', a.take, '-filter_complex', ';'.join(fc), '-map', '[v]', '-map', '[a]',
                    '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-c:a', 'aac', '-b:a', '160k', a.out], check=True)

    new = {k: round((v - removed_before(v)) / tempo, 3) for k, v in ANCHORS.items() if k != 'tail'}
    new['tail'] = round(kept / tempo, 3)
    Path(a.anchors).write_text(json.dumps(new, indent=1))
    for k in ('intro', 'cell', 'scan', 'dashboard', 'map_rt', 'result', 'pip_back', 'end', 'tail'):
        print(f'{k:9s} {ANCHORS[k]:7.2f} -> {new[k]:7.2f}')
    print('wrote', a.out, a.anchors)


if __name__ == '__main__':
    main()
