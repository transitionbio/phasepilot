"""Results chart, linear version (Will's note: linear y is more impactful, labels simpler and much larger).

Instrument run time in days to map a phase boundary vs the number of variables, legacy scan (k^n conditions,
3.1 s each) against PhasePilot (~0.68 k^(n-1) setpoints, 2.6 s each), constants from the 3-variable replay.

    python render_scaling_linear.py --out tbio/scaling3.png
"""
import argparse

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BLUE, GREEN, INK, MUTED = '#1366AB', '#008759', '#404040', '#6E7276'
K = 10
T_RASTER = 51.3 * 60 / K**3
C_LOOP = 68 / K**2
T_LOOP = 2.6


def days(n, per_cond, c=1.0, power=0):
    return c * K**(n + power) * per_cond / 86400


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default='tbio/scaling3.png')
    a = p.parse_args()
    n = np.arange(2, 7)
    raster = days(n, T_RASTER)
    loop = days(n, T_LOOP, C_LOOP, -1)

    plt.rcParams['font.family'] = 'Arial'
    fig, ax = plt.subplots(figsize=(10, 6.6), dpi=110)
    ax.axhline(7, color='#C9E3D6', lw=2, zorder=0)
    ax.text(1.75, 7.6, '1 week', color=GREEN, fontsize=18, weight='bold')
    ax.axhline(30, color='#C9E3D6', lw=2, zorder=0)
    ax.text(1.75, 30.6, '1 month', color=GREEN, fontsize=18, weight='bold')
    ax.plot(n, raster, color=INK, lw=4, marker='o', ms=10)
    ax.plot(n, loop, color=BLUE, lw=4, marker='o', ms=10)
    ax.text(4.6, 25.5, 'Legacy scan', color=INK, fontsize=22, weight='bold', ha='center')
    ax.text(4.6, 22.5, 'every condition, k$^n$', color=INK, fontsize=16, ha='center')
    ax.text(2.2, 3.0, 'PhasePilot', color=BLUE, fontsize=22, weight='bold')
    ax.text(2.2, 1.1, 'the boundary only, ~k$^{n-1}$', color=BLUE, fontsize=16)
    ax.annotate('', xy=(6, loop[-1] + 0.4), xytext=(6, raster[-1] - 0.6),
                arrowprops=dict(arrowstyle='->', color=GREEN, lw=3))
    ax.text(6.08, (raster[-1] + loop[-1]) / 2, f'{raster[-1]:.0f} days\nto\n{loop[-1]:.0f} days', color=GREEN, fontsize=18,
            weight='bold', va='center')
    ax.set_xlim(1.7, 6.75)
    ax.set_ylim(0, 39)
    ax.set_xticks(n)
    ax.set_xlabel('variables mapped', fontsize=20, color=INK)
    ax.set_ylabel('instrument time (days)', fontsize=20, color=INK)
    ax.tick_params(colors=INK, labelsize=18)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#B0B4B8')
    ax.set_title('10 levels per variable', fontsize=16, color=MUTED, loc='left')
    fig.tight_layout()
    fig.savefig(a.out, facecolor='white')
    print('wrote', a.out, 'raster days', raster.round(3), 'loop days', loop.round(3))


if __name__ == '__main__':
    main()
