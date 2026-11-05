"""Animated Transition Bio slides: white page, logo top-left, blue heading, lines that fade in at given times on the
left, and one animated diagram on the right. Muse Wonder writes the slide specs; this renders them.

Diagrams (each drawn for a progress p in [0, 1] over the slide):
  cell          a cell with condensates forming (optional aggregate at the end)
  demix         mixed molecules (left) separating into dense droplets (right)
  phase_diagram protein vs partner scatter with the boundary drawn in; a compound shifts the boundary up
  droplet       one droplet growing, "100 pL", and a counter up to ~1,000,000x less protein per data point
  kn_curve      conditions = k^n against variables mapped, with a practical-budget line and the out-of-reach band
  loop          the closed loop: Muse at the centre, four stations appearing in turn, a dot running round
  sam           droplets under a scanning line: outlines turn green as SAM reads them
  sampling      Bayesian rounds: points accumulate near the boundary and the uncertainty band narrows
  nodes         the variables of biology appearing as linked nodes
  applications  the closed loop at the centre with application boxes appearing around it

    python tbio_anim.py --demo out_dir     # one still per diagram at p=1 for a look
"""
import math
import random
import subprocess
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Ellipse, Circle, FancyBboxPatch, Rectangle
import numpy as np
from PIL import Image, ImageDraw

from build_tbio import W, H, BLUE, GREEN, INK, MUTED, PANEL, HERE, font, logo, wrap_text, FF

C_BLUE, C_GREEN, C_INK, C_MUTED, C_PANEL, C_LIGHT = '#1366AB', '#008759', '#404040', '#6E7276', '#DBEFF9', '#9CCDE8'
DIAG_W, DIAG_H = 1000, 760          # diagram area, right of the text column
DIAG_FPS = 10


def ease(p):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, p)))


def fig_ax():
    fig, ax = plt.subplots(figsize=(DIAG_W / 100, DIAG_H / 100), dpi=100)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 7.6)
    ax.axis('off')
    fig.subplots_adjust(0, 0, 1, 1)
    return fig, ax


def finish(fig, path):
    fig.savefig(path, facecolor='white')
    plt.close(fig)


# ----------------------------------------------------------------------------- diagrams
def d_cell(ax, p, prm):
    ax.add_patch(Ellipse((5, 3.8), 8.4, 6.4, facecolor='#F2F7FA', edgecolor=C_MUTED, lw=2))
    ax.add_patch(Ellipse((4.3, 3.6), 3.2, 2.4, facecolor='none', edgecolor=C_MUTED, lw=1.2, ls='--'))
    ax.text(4.3, 2.1, 'nucleus', color=C_MUTED, fontsize=11, ha='center')
    rnd = random.Random(3)
    spots = [(rnd.uniform(1.6, 8.4), rnd.uniform(1.2, 6.4)) for _ in range(7)]
    for i, (x, y) in enumerate(spots):
        r = 0.42 * ease(p * 1.6 - i * 0.12)
        if r > 0:
            ax.add_patch(Circle((x, y), r, facecolor=C_GREEN, edgecolor='none', alpha=0.9))
    for _ in range(60):
        ax.plot(rnd.uniform(1.2, 8.8), rnd.uniform(1, 6.6), '.', color=C_LIGHT, ms=4)
    if prm.get('aggregate') and p > 0.7:
        a = ease((p - 0.7) / 0.3)
        ax.plot(7.6, 5.4, marker=(8, 1, 0), ms=38 * a, color=C_INK)
        ax.text(7.6, 4.5, 'aggregate', color=C_INK, fontsize=12, ha='center', alpha=a, weight='bold')
    ax.text(8.2, 1.4, 'condensate', color=C_GREEN, fontsize=12, ha='center', alpha=ease(p * 1.6))


def d_demix(ax, p, prm):
    rnd = random.Random(5)
    pts = [(rnd.uniform(0.4, 3.9), rnd.uniform(1.4, 6.2)) for _ in range(120)]
    ax.add_patch(FancyBboxPatch((0.3, 1.2), 3.8, 5.2, boxstyle='round,pad=0.05', facecolor='#F2F7FA', edgecolor=C_MUTED, lw=1.5))
    ax.add_patch(FancyBboxPatch((5.9, 1.2), 3.8, 5.2, boxstyle='round,pad=0.05', facecolor='#F2F7FA', edgecolor=C_MUTED, lw=1.5))
    for x, y in pts:
        ax.plot(x, y, '.', color=C_INK, ms=5)
    centres = [(6.9, 2.4), (8.6, 3.0), (7.3, 5.0), (8.9, 5.4), (6.6, 3.9)]
    e = ease(p)
    for i, (cx, cy) in enumerate(centres):
        r = 0.75 * e
        if r > 0:
            ax.add_patch(Circle((cx, cy), r, facecolor='#CFEBDD', edgecolor=C_GREEN, lw=2))
        for k in range(18):
            ang, rr = rnd.uniform(0, 6.28), rnd.uniform(0, 1)
            x0, y0 = 5.9 + rnd.uniform(0.1, 3.7), 1.2 + rnd.uniform(0.1, 5.0)
            x1, y1 = cx + r * 0.85 * rr * math.cos(ang), cy + r * 0.85 * rr * math.sin(ang)
            ax.plot(x0 + (x1 - x0) * e, y0 + (y1 - y0) * e, '.', color=C_GREEN, ms=5)
    ax.annotate('', xy=(5.7, 3.8), xytext=(4.3, 3.8), arrowprops=dict(arrowstyle='->', color=C_INK, lw=2.5))
    ax.text(2.2, 6.9, 'mixed', color=C_INK, fontsize=14, ha='center', weight='bold')
    ax.text(7.8, 6.9, 'demixed: dense droplets', color=C_GREEN, fontsize=14, ha='center', weight='bold', alpha=e)


def _boundary(x, lift=0.0):
    return 2.2 + 1.1 * (x - 4.5) ** 2 / 10 + lift


def d_phase_diagram(ax, p, prm):
    ax.plot([0.8, 0.8], [0.8, 7.0], color=C_MUTED, lw=1.5)
    ax.plot([0.8, 9.6], [0.8, 0.8], color=C_MUTED, lw=1.5)
    ax.text(5.2, 0.25, 'partner (RNA, salt, crowder ...)', color=C_MUTED, fontsize=12, ha='center')
    ax.text(0.35, 3.9, 'protein', color=C_MUTED, fontsize=12, rotation=90, va='center')
    rnd = random.Random(7)
    n = int(90 * min(1.0, p * 1.5))
    for i in range(n):
        x, y = rnd.uniform(1.2, 9.3), rnd.uniform(1.0, 6.7)
        ps = y > _boundary(x)
        ax.plot(x, y, 'o', ms=6, color=C_GREEN if ps else 'white', mec=C_GREEN if ps else C_MUTED, mew=1.2)
    if p > 0.35:
        q = ease((p - 0.35) / 0.3)
        xs = np.linspace(1.0, 9.4, 80)
        k = max(2, int(len(xs) * q))
        ax.plot(xs[:k], _boundary(xs[:k]), color=C_BLUE, lw=3)
        ax.text(2.2, 6.6, 'phase separated', color=C_GREEN, fontsize=13, weight='bold', alpha=q)
        ax.text(6.9, 1.3, 'one phase', color=C_MUTED, fontsize=13, alpha=q)
    if prm.get('compound') and p > 0.7:
        q = ease((p - 0.7) / 0.3)
        xs = np.linspace(1.0, 9.4, 80)
        ax.plot(xs, _boundary(xs, 1.3 * q), color=C_BLUE, lw=3, ls='--', alpha=q)
        for x in (3.0, 6.0):
            ax.annotate('', xy=(x, _boundary(x, 1.3 * q) + 0.1), xytext=(x, _boundary(x) + 0.1),
                        arrowprops=dict(arrowstyle='->', color=C_INK, lw=2, alpha=q))
        ax.text(8.2, _boundary(8.2, 1.3 * q) + 0.35, 'with compound', color=C_BLUE, fontsize=12, ha='center', alpha=q, weight='bold')


def d_droplet(ax, p, prm):
    r = 0.4 + 2.4 * ease(min(1.0, p * 2))
    ax.add_patch(Circle((3.2, 3.9), r, facecolor='#F2F7FA', edgecolor=C_BLUE, lw=3))
    ax.text(3.2, 0.9, 'one droplet, to scale', color=C_MUTED, fontsize=12, ha='center')
    ax.text(3.2, 3.9, '100 pL', color=C_BLUE, fontsize=30, ha='center', va='center', weight='bold', alpha=ease((p - 0.3) / 0.3))
    if p > 0.5:
        q = ease((p - 0.5) / 0.5)
        val = int(1_000_000 ** q) if q < 1 else 1_000_000
        ax.text(7.6, 4.6, f'~{val:,}x', color=C_GREEN, fontsize=34, ha='center', weight='bold')
        ax.text(7.6, 3.6, 'less protein per data point', color=C_INK, fontsize=14, ha='center')
        ax.text(7.6, 3.0, 'than conventional labware', color=C_INK, fontsize=14, ha='center')
        ax.text(7.6, 1.9, 'each drop = one experimental condition', color=C_MUTED, fontsize=12, ha='center', alpha=q)


def d_kn_curve(ax, p, prm):
    k = prm.get('levels', 10)
    ax.plot([1.2, 1.2], [0.9, 7.0], color=C_MUTED, lw=1.5)
    ax.plot([1.2, 9.6], [0.9, 0.9], color=C_MUTED, lw=1.5)
    for n in range(1, 7):
        ax.text(1.2 + (n - 1) * 1.6, 0.45, str(n), color=C_MUTED, fontsize=12, ha='center')
    ax.text(5.4, 0.05, 'variables mapped', color=C_MUTED, fontsize=12, ha='center')
    ax.text(0.7, 3.9, 'conditions needed', color=C_MUTED, fontsize=12, rotation=90, va='center')
    budget = 4.6
    ax.add_patch(Rectangle((1.2, budget), 8.4, 7.0 - budget, facecolor='#EEF1F3', edgecolor='none'))
    ax.plot([1.2, 9.6], [budget, budget], color=C_GREEN, lw=2, ls='--')
    ax.text(1.5, budget + 0.2, 'practical experimental budget', color=C_GREEN, fontsize=12, weight='bold')
    ax.text(5.4, 6.4, 'out of reach', color=C_MUTED, fontsize=13, ha='center')
    q = ease(p)
    xs = np.linspace(1, 1 + 5 * q, 120)
    ys = 0.9 + 6.0 * (k ** (xs - 1)) / (k ** 5)
    ys = np.minimum(ys, 7.0)
    ax.plot(1.2 + (xs - 1) * 1.6, ys, color=C_INK, lw=3.5)
    n_now = 1 + 5 * q
    ax.text(9.5, 7.3, f'{int(k ** n_now):,} conditions at {n_now:.0f} variables', color=C_INK, fontsize=12, ha='right', weight='bold')
    ax.text(9.5, 0.05, f'{k} levels per variable', color=C_MUTED, fontsize=11, ha='right')


def d_loop(ax, p, prm):
    ax.add_patch(Ellipse((5, 3.9), 6.0, 5.0, facecolor='none', edgecolor=C_GREEN, lw=2.5))
    ax.text(5, 4.1, 'Muse', color=C_INK, fontsize=34, ha='center', va='center', weight='bold')
    ax.text(5, 3.3, 'one closed loop per protein', color=C_MUTED, fontsize=11, ha='center')
    stations = [((5, 6.4), 'Muse proposes conditions'), ((8.0, 3.9), 'PhaseScan runs\nthe droplets'),
                ((5, 1.4), 'SAM checks the images'), ((2.0, 3.9), 'Bayesian model\nupdates')]
    for i, ((x, y), lab) in enumerate(stations):
        a = ease(p * 4 - i)
        if a > 0:
            ax.text(x, y, lab, color=C_INK, fontsize=12, ha='center', va='center', alpha=a,
                    bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor=C_GREEN, lw=1.5, alpha=a))
    ang = math.pi / 2 - 2 * math.pi * (p * 1.5 % 1.0)
    ax.plot(5 + 3.0 * math.cos(ang), 3.9 + 2.5 * math.sin(ang), 'o', color=C_GREEN, ms=11)


def d_sam(ax, p, prm):
    rnd = random.Random(11)
    ax.add_patch(FancyBboxPatch((0.4, 0.6), 9.2, 6.4, boxstyle='round,pad=0.05', facecolor='#F7FAFC', edgecolor=C_MUTED, lw=1.5))
    ax.text(0.7, 7.15, 'MICROSCOPY, LIVE', color=C_MUTED, fontsize=10)
    drops = []
    for _ in range(40):
        x, y, r = rnd.uniform(1.0, 9.0), rnd.uniform(1.1, 6.5), rnd.uniform(0.28, 0.55)
        if all((x - a) ** 2 + (y - b) ** 2 > (r + c + 0.1) ** 2 for a, b, c in drops):
            drops.append((x, y, r))
    scan = 0.4 + 9.2 * ease(p)
    done = 0
    for x, y, r in drops:
        seen = x + r < scan
        done += seen
        ax.add_patch(Circle((x, y), r, facecolor='#E6F3EC' if seen else 'white', edgecolor=C_GREEN if seen else C_MUTED, lw=2.4 if seen else 1.2))
        if rnd.random() < 0.55:
            for _ in range(rnd.randint(1, 3)):
                ax.add_patch(Circle((x + rnd.uniform(-r * 0.5, r * 0.5), y + rnd.uniform(-r * 0.5, r * 0.5)), r * 0.2,
                                    facecolor=C_GREEN if seen else C_MUTED, edgecolor='none'))
    ax.plot([scan, scan], [0.6, 7.0], color=C_GREEN, lw=2.5)
    ax.text(9.3, 7.15, f'segmented {done}', color=C_GREEN, fontsize=11, ha='right', weight='bold')


def d_sampling(ax, p, prm):
    ax.plot([0.8, 0.8], [0.8, 7.0], color=C_MUTED, lw=1.5)
    ax.plot([0.8, 9.6], [0.8, 0.8], color=C_MUTED, lw=1.5)
    ax.text(5.2, 0.25, 'partner', color=C_MUTED, fontsize=12, ha='center')
    ax.text(0.35, 3.9, 'protein', color=C_MUTED, fontsize=12, rotation=90, va='center')
    rnd = random.Random(13)
    rounds = 1 + int(p * 3.99)
    xs = np.linspace(1.0, 9.4, 80)
    width = 1.6 / rounds
    ax.fill_between(xs, _boundary(xs) - width, _boundary(xs) + width, color=C_GREEN, alpha=0.18)
    ax.plot(xs, _boundary(xs), color=C_GREEN, lw=2.5)
    for r in range(rounds):
        spread = 2.4 / (r + 1)
        for _ in range(14):
            x = rnd.uniform(1.2, 9.3)
            y = _boundary(x) + rnd.uniform(-spread, spread)
            if 1.0 < y < 6.7:
                ps = y > _boundary(x)
                a = 1.0 if r == rounds - 1 else 0.35
                ax.plot(x, y, 'o', ms=6, color=C_GREEN if ps else 'white', mec=C_GREEN if ps else C_MUTED, mew=1.2, alpha=a)
    ax.text(9.4, 6.7, f'round {rounds}', color=C_INK, fontsize=14, ha='right', weight='bold')
    ax.text(9.4, 6.2, 'model uncertainty', color=C_GREEN, fontsize=11, ha='right')


def d_nodes(ax, p, prm):
    names = prm.get('names', ['protein', 'RNA', 'binding partners', 'phosphorylation', 'pH', 'temperature', 'crowder', 'compound'])
    pos = [(5 + 3.6 * math.cos(2 * math.pi * i / len(names)), 3.9 + 2.6 * math.sin(2 * math.pi * i / len(names))) for i in range(len(names))]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a = ease(p * 1.3 - 0.3) * 0.5
            if a > 0:
                ax.plot([pos[i][0], pos[j][0]], [pos[i][1], pos[j][1]], color=C_LIGHT, lw=1, alpha=a)
    for i, (n, (x, y)) in enumerate(zip(names, pos)):
        a = ease(p * len(names) * 0.8 - i * 0.8)
        if a > 0:
            ax.text(x, y, n, color=C_INK, fontsize=13, ha='center', va='center', alpha=a,
                    bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor=C_GREEN, lw=1.5, alpha=a))


def d_applications(ax, p, prm):
    ax.add_patch(Circle((5, 3.9), 1.6, facecolor='white', edgecolor=C_GREEN, lw=3))
    ax.text(5, 4.1, 'closed loop', color=C_INK, fontsize=15, ha='center', va='center', weight='bold')
    ax.text(5, 3.5, 'instrument + agent', color=C_MUTED, fontsize=10, ha='center', va='center')
    apps = [((5, 6.8), 'Phase separation', True), ((8.6, 5.3), 'Formulation', False), ((8.6, 2.4), 'Cell culture', False),
            ((1.4, 2.4), 'Enzyme engineering', False), ((1.4, 5.3), 'Assay design', False)]
    for i, ((x, y), lab, here) in enumerate(apps):
        a = ease(p * 5 - i)
        if a > 0:
            ax.plot([5 + (x - 5) * 0.35, x], [3.9 + (y - 3.9) * 0.45, y], color=C_GREEN, lw=1.5, alpha=a)
            ax.text(x, y, lab, color='white' if here else C_INK, fontsize=12, ha='center', va='center', alpha=a, weight='bold' if here else 'normal',
                    bbox=dict(boxstyle='round,pad=0.45', facecolor=C_GREEN if here else 'white', edgecolor=C_GREEN, lw=1.5, alpha=a))
            if here:
                ax.text(x, y + 0.55, 'demonstrated here', color=C_GREEN, fontsize=10, ha='center', alpha=a)


DIAGRAMS = dict(cell=d_cell, demix=d_demix, phase_diagram=d_phase_diagram, droplet=d_droplet, kn_curve=d_kn_curve,
                loop=d_loop, sam=d_sam, sampling=d_sampling, nodes=d_nodes, applications=d_applications)


def diagram_frame(name, p, prm, path):
    fig, ax = fig_ax()
    DIAGRAMS[name](ax, p, prm or {})
    finish(fig, path)


# ----------------------------------------------------------------------------- slide
def render_slide(out, spec, fades=(True, True)):
    """spec: heading, lines [{t, text, style?}], diagram, diagram_params, seconds. Writes an mp4 at 30 fps."""
    secs = float(spec['seconds'])
    work = Path(tempfile.mkdtemp())
    n_diag = max(1, int(secs * DIAG_FPS))
    diag = spec.get('diagram')
    frames = []
    for i in range(n_diag):
        f = work / f'd{i:04d}.png'
        if diag:
            diagram_frame(diag, i / max(1, n_diag - 1), spec.get('diagram_params'), f)
        frames.append(f)
    base = Image.new('RGB', (W, H), 'white')
    logo(base)
    d = ImageDraw.Draw(base)
    d.text((62, 168), spec['heading'], font=font(46, True), fill=BLUE)
    n = int(secs * 30)
    lines = spec.get('lines', [])
    seq = work / 'frames.txt'
    with open(seq, 'w') as fh:
        last = None
        for i in range(n):
            t = i / 30
            img = base.copy()
            if diag:
                di = Image.open(frames[min(n_diag - 1, int(t * DIAG_FPS))]).convert('RGB')
                img.paste(di, (W - 62 - DIAG_W, 250))
            dd = ImageDraw.Draw(img, 'RGBA')
            y = 262
            for ln in lines:
                a = ease((t - float(ln.get('t', 0))) / 0.5)
                st = ln.get('style', 'body')
                f_, col, wrapw, lh = {'big': (font(40, True), INK, 32, 52), 'body': (font(30), INK, 42, 40),
                                      'green': (font(30, True), GREEN, 42, 40), 'muted': (font(24), MUTED, 54, 32)}[st]
                if a > 0:
                    col_a = (*col, int(255 * a))
                    for row in __import__('textwrap').wrap(ln['text'], wrapw):
                        dd.text((62, y), row, font=f_, fill=col_a)
                        y += lh
                else:
                    y += lh * len(__import__('textwrap').wrap(ln['text'], wrapw))
                y += 18
            fp = work / f'f{i:05d}.png'
            img.save(fp)
            fh.write(f"file '{fp}'\nduration {1 / 30:.5f}\n")
    from build_final import enc
    enc(out, ['-f', 'concat', '-safe', '0', '-i', str(seq)], '[0:v]fps=30,scale=1920:1080,format=yuv420p[v]', secs, fades)
    return secs


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--demo')
    a = ap.parse_args()
    if a.demo:
        Path(a.demo).mkdir(parents=True, exist_ok=True)
        for name in DIAGRAMS:
            diagram_frame(name, 1.0, {'aggregate': True, 'compound': True}, Path(a.demo) / f'{name}.png')
        print('wrote demo stills to', a.demo)
