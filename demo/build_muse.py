"""Render the film from a Muse Wonder plan (muse_director.py -> muse/plan.json) in the Transition Bio style.

Beat types: title, explainer (Will's animation, ss/len/slow), phone (portrait lab footage with a side panel),
loop (our dashboard beats: dash/sam/muse/map), card (white page, heading + bullets + note, optional muse-image
artwork), results (stats on the left, our scaling chart on the right), end.

    python build_muse.py --plan muse/plan.json --out phasepilot_muse.mp4
"""
import argparse
import base64
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

from build_tbio import W, H, BLUE, GREEN, INK, MUTED, PANEL, HERE, font, logo, wrap_text, title_card, run
from build_final import EXPLAINER, PHONE, TBIO, seg_video, seg_still, seg_portrait, side_card, xfade_join

LOOP = {'dash': (3, 6), 'sam': (9, 11), 'muse': (20, 12), 'map': (32, 20)}
ENV = dict(l.strip().split('=', 1) for l in open(HERE.parent / 'loop/.env') if '=' in l)


def muse_image(prompt, path):
    """One still from muse-image-1.0 (Meta Model API); returns False if the call fails so the card renders without it."""
    body = dict(model='muse-image-1.0', prompt=prompt, n=1, size='1024x1024')
    req = urllib.request.Request(ENV.get('MUSE_BASE_URL', 'https://api.meta.ai/v1') + '/images/generations',
                                 data=json.dumps(body).encode(),
                                 headers={'Authorization': 'Bearer ' + ENV['MUSE_API_KEY'], 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            j = json.load(r)
        Path(path).write_bytes(base64.b64decode(j['data'][0]['b64_json']))
        Image.open(path).convert('RGB').save(path)
        return True
    except Exception as e:
        print('muse-image failed:', e)
        return False


def page(heading):
    img = Image.new('RGB', (W, H), 'white')
    d = ImageDraw.Draw(img)
    logo(img)
    d.text((62, 168), heading, font=font(46, True), fill=BLUE)
    return img, d


def card(path, b, art=None):
    """White page: heading, bullets in a light-blue panel on the left, artwork (if any) on the right."""
    img, d = page(b['heading'])
    px, py, pw = 62, 262, 1040 if art else W - 124
    bullets = b.get('bullets', [])[:3]
    if len(bullets) == 1 and not art:
        # statement layout: the one line large, its comma-separated items as green chips, the note beneath
        items = [s.strip() for s in bullets[0].replace(' and ', ', ').split(',') if s.strip()]
        d.rounded_rectangle([px, py, px + pw, 760], radius=18, fill=PANEL)
        y = wrap_text(d, px + 60, py + 70, b.get('note', ''), font(44, True), INK, 56, 58)
        x, y = px + 60, y + 50
        for it in items:
            w = d.textlength(it, font=font(38, True)) + 64
            if x + w > px + pw - 60:
                x, y = px + 60, y + 100
            d.rounded_rectangle([x, y, x + w, y + 74], radius=37, fill=GREEN)
            d.text((x + 32, y + 16), it, font=font(38, True), fill='white')
            x += w + 26
        d.text((62, 830), 'Each added variable costs the loop what the previous one cost the raster.', font=font(30, True), fill=GREEN)
        img.save(path)
        return
    d.rounded_rectangle([px, py, px + pw, 1000], radius=18, fill=PANEL)
    y = py + 60
    for t in bullets:
        d.ellipse([px + 38, y + 13, px + 56, y + 31], fill=GREEN)
        y = wrap_text(d, px + 88, y, t, font(32), INK, 48 if art else 80, 44) + 34
    if b.get('note'):
        wrap_text(d, px + 34, 900, b['note'], font(22), MUTED, 70 if art else 120, 28)
    if art:
        a = Image.open(art).convert('RGB')
        s = min(700 / a.width, 700 / a.height)
        a = a.resize((int(a.width * s), int(a.height * s)), Image.LANCZOS)
        img.paste(a, (W - 62 - a.width, 262 + (738 - a.height) // 2))
    img.save(path)


def results_stats(path, b, n_show):
    """Slide 1 of the results: the big numbers, revealed one at a time (n_show of them visible), large type."""
    img, d = page(b.get('heading', 'Measured gains'))
    y = 290
    for s in b['stats'][:n_show]:
        d.text((62, y), s['big'], font=font(110 if len(s['big']) <= 3 else 92, True), fill=BLUE)
        line = s['line']
        if line.lower().startswith(s['big'].lower()):      # the big number already says it
            line = line[len(s['big']):].strip()
        yy = wrap_text(d, 420, y + 18, line, font(44, True), INK, 52, 54)
        wrap_text(d, 420, yy + 6, s.get('sub', ''), font(30), MUTED, 75, 38)
        y += 230
    if n_show >= 3 and b.get('footnote'):
        wrap_text(d, 62, 990, b['footnote'], font(20), MUTED, 150, 26)
    img.save(path)


def results_chart(path, b):
    """Slide 2 of the results: the linear scaling chart, large, with one line above and the green line below."""
    img, d = page(b.get('heading', 'Every added variable'))
    chart = Image.open(HERE / 'tbio/scaling3.png').convert('RGB')
    ch = 760
    chart = chart.resize((int(chart.width * ch / chart.height), ch), Image.LANCZOS)
    img.paste(chart, (62, 225))
    x = 62 + chart.width + 50
    y = wrap_text(d, x, 300, b.get('line', ''), font(42, True), INK, 24, 54)
    wrap_text(d, x, y + 30, b.get('sub', ''), font(30), MUTED, 30, 40)
    if b.get('green_line'):
        wrap_text(d, 62, 985, b['green_line'], font(30, True), GREEN, 100, 38)
    img.save(path)


def seg_explainer(out, b):
    """Will's explainer; when the segment covers the 'every new dimension' beat, the dark version's extra line
    (Time is proportional to t0^N for N dimensions) is drawn on the light frames as in the dark cut."""
    ss, ln, slow = float(b['ss']), float(b['len']), float(b.get('slow', 1.0))
    src_a, src_b = 36.5, 42.0
    if not (ss <= src_a and ss + ln >= src_b - 0.5):
        return seg_video(out, EXPLAINER, ss, ln, slow)
    ov = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    mono = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'
    from PIL import ImageFont
    f = ImageFont.truetype(mono, 34)
    d.text((150, 885), 'Time ∝ t₀ᴺ for N dimensions', font=f, fill=(0, 135, 89, 255))
    ovp = Path(out).with_suffix('.ov.png')
    ov.save(ovp)
    t1, t2 = (src_a - ss) * slow, (min(src_b, ss + ln) - ss) * slow
    duration = ln * slow
    from build_final import enc
    enc(out, ['-ss', f'{ss:.3f}', '-t', f'{ln:.3f}', '-i', str(EXPLAINER), '-loop', '1', '-framerate', '30', '-i', str(ovp)],
        f"[0:v]setpts={slow:.4f}*PTS,scale={W}:{H},fps=30[a];[a][1:v]overlay=0:0:enable='between(t,{t1:.2f},{t2:.2f})',format=yuv420p[v]",
        duration)
    return duration


def end(path, b):
    bg = Image.open(HERE / 'tbio/title_bg.jpg').convert('RGB')
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1), Image.LANCZOS).crop((0, 0, W, H))
    d = ImageDraw.Draw(bg)
    logo(bg, 62, 56, 520)
    d.text((110, 400), b.get('heading', 'PhasePilot'), font=font(96, True), fill=INK)
    y = 530
    for line in b.get('lines', [])[:2]:
        y = wrap_text(d, 114, y, line, font(34), INK, 60, 44) + 8
    if b.get('green_line'):
        d.text((114, y + 10), b['green_line'], font=font(30, True), fill=GREEN)
        y += 70
    for c in b.get('credits', [])[:3]:
        d.text((114, y + 10), c, font=font(24), fill=MUTED)
        y += 36
    bg.save(path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--plan', default=str(HERE / 'muse/plan.json'))
    p.add_argument('--out', default=str(HERE / 'phasepilot_muse.mp4'))
    a = p.parse_args()
    plan = json.load(open(a.plan))
    work = Path(tempfile.mkdtemp())
    art_dir = Path(a.plan).parent / 'art'
    art_dir.mkdir(exist_ok=True)
    parts, durs = [], []
    for i, b in enumerate(plan['beats']):
        out = work / f'{i:02d}_{b["type"]}.mp4'
        t = b['type']
        if t == 'title':
            c = work / f'{i:02d}.png'
            title_card(c, b.get('heading', 'PhasePilot'), b.get('subtitle', ''))
            d = float(b['seconds']); seg_still(out, c, d)
        elif t == 'explainer':
            d = seg_explainer(out, b)
        elif t == 'anim':
            from tbio_anim import render_slide
            d = render_slide(out, b)
        elif t == 'phone':
            c = work / f'{i:02d}.png'
            side_card(c, b['heading'], b.get('bullets', [])[:3], b.get('note', ''))
            crop = (1080, 1500, 0, 60) if float(b['ss']) < 14 else None
            d = float(b['seconds']); seg_portrait(out, PHONE, float(b['ss']), d, c, crop=crop)
        elif t == 'loop':
            ss, ln = LOOP[b['beat']]
            d = seg_video(out, TBIO, ss, ln, float(b.get('slow', 1.0)))
        elif t == 'card':
            art = None
            if b.get('image_prompt'):
                art = art_dir / f'{i:02d}.png'
                if not art.exists() and not muse_image(b['image_prompt'], art):
                    art = None
            c = work / f'{i:02d}.png'
            card(c, b, art)
            d = float(b['seconds']); seg_still(out, c, d)
        elif t == 'results_stats':
            # the three numbers appear one at a time: three stills, no fades between them
            d = float(b['seconds'])
            n = min(3, len(b['stats']))
            subs = []
            for k in range(1, n + 1):
                c = work / f'{i:02d}_{k}.png'
                results_stats(c, b, k)
                o = work / f'{i:02d}_{k}.mp4'
                seg_still(o, c, d / n, (k == 1, k == n))
                subs.append(o)
            lst = work / f'{i:02d}_list.txt'
            lst.write_text(''.join(f"file '{s}'\n" for s in subs))
            run(['-f', 'concat', '-safe', '0', '-i', str(lst), '-c', 'copy', str(out)])
        elif t == 'results_chart':
            c = work / f'{i:02d}.png'
            results_chart(c, b)
            d = float(b['seconds']); seg_still(out, c, d)
        elif t == 'end':
            c = work / f'{i:02d}.png'
            end(c, b)
            d = float(b['seconds']); seg_still(out, c, d)
        else:
            raise SystemExit(f'unknown beat type {t}')
        parts.append(out); durs.append(d)
        print(f'{sum(durs) - d:6.1f}s  {t:9s} {b.get("beat", "")} {b.get("heading", "")}  ({d:.1f} s)')
    total = xfade_join(parts, durs, a.out)
    print(f'wrote {a.out}  ({total:.1f} s)  cards in {work}')


if __name__ == '__main__':
    main()
