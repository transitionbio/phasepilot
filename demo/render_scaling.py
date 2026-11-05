"""Scaling chart for the results card: instrument run time (pumps flowing, camera imaging) to map a phase boundary
vs the number of variables.

Constants from the replay benchmark (replay benchmark, see docs/results.md): the full
3-variable raster streamed ~1000 compositions in 51.3 min (3.1 s each) and used 52 uL protein. The loop pinned the
same boundary (>= 0.997 near it) with 68 setpoints, 2.6 s of flow each: 2.9 min of instrument time, 2.5 uL. Its
wall clock was 23 min because each of its 7 rounds waited 180 s for droplets to incubate before the next decision.
A raster needs k^n conditions; the loop samples the boundary, a surface of n-1 dimensions, ~c k^(n-1).

    python render_scaling.py --out tbio/scaling2.png
"""
import argparse

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BLUE, GREEN, ORANGE, INK, MUTED = '#1366AB', '#008759', '#EF8E00', '#404040', '#6E7276'
K = 10                          # levels per variable
T_RASTER = 51.3 * 60 / K**3     # 3.1 s of instrument time per raster condition
C_LOOP = 68 / K**2              # loop setpoints as a fraction of k^(n-1) (0.68)
T_LOOP = 2.6                    # s of instrument time per loop setpoint


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', default='tbio/scaling2.png')
    a = p.parse_args()
    n = np.arange(2, 7)
    raster = K**n * T_RASTER / 3600
    loop = C_LOOP * K**(n - 1) * T_LOOP / 3600
    ratio = raster[1] / loop[1]

    plt.rcParams['font.family'] = 'Arial'
    fig, ax = plt.subplots(figsize=(10, 6.6), dpi=110)
    for y, lab in ((1, '1 hour'), (8, 'working day'), (24 * 7, 'week'), (24 * 30, 'month')):
        ax.axhline(y, color='#C9E3D6', lw=1.4, zorder=0)
        ax.text(6.08, y, lab, color=GREEN, fontsize=12, weight='bold', va='center')
    ax.plot(n, raster, color=INK, lw=3, marker='o', ms=7)
    ax.plot(n, loop, color=BLUE, lw=3, marker='o', ms=7)
    # the same budget buys one more variable
    for i in (1, 2, 3):
        ax.annotate('', xy=(n[i] + 1, loop[i + 1]), xytext=(n[i], raster[i]),
                    arrowprops=dict(arrowstyle='->', color=GREEN, lw=1.6, ls='--'))
    ax.text(2.0, 60, '+1 variable in the time and protein\nof a legacy scan (10 levels each);\n+2 variables at 4 levels each',
            color=GREEN, fontsize=13, weight='bold', va='top', ha='left')
    ax.text(4.2, 1500, 'legacy raster: every condition, k$^n$', color=INK, fontsize=13, weight='bold')
    ax.text(4.25, loop[2] * 0.16, f'PhasePilot: the boundary only, ~k$^{{n-1}}$\n{ratio:.0f}x less instrument time, 20x less protein',
            color=BLUE, fontsize=13, weight='bold', va='top')
    ax.annotate('measured: 2.9 min vs 51 min', xy=(3, loop[1]), xytext=(3.08, loop[1] * 0.28), color=BLUE, fontsize=11,
                arrowprops=dict(arrowstyle='-', color=BLUE, lw=1))
    ax.set_yscale('log')
    ax.set_xlim(1.85, 6.7)
    ax.set_ylim(0.004, 3000)
    ax.set_xticks(n)
    ax.set_xlabel('variables mapped (protein, RNA, crowder, salt, pH, compound ...)', fontsize=13, color=INK)
    ax.set_ylabel('instrument run time to map the boundary (hours, log)', fontsize=13, color=INK)
    ax.set_yticks([0.01, 0.1, 1, 10, 100, 1000])
    ax.set_yticklabels(['0.01', '0.1', '1', '10', '100', '1000'])
    ax.tick_params(colors=INK, labelsize=12)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color('#B0B4B8')
    ax.set_title('10 levels per variable; per-condition instrument time from the 3-variable replay', fontsize=12, color=MUTED, loc='left')
    fig.tight_layout()
    fig.savefig(a.out, facecolor='white')
    print('wrote', a.out, 'ratio', round(ratio, 1), 'raster h', raster.round(3), 'loop h', loop.round(3))


if __name__ == '__main__':
    main()
