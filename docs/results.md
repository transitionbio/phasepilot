# Results and method

## The replay benchmark

The numbers in the film come from a replay of a complete three-variable PhaseScan scan (G3BP1 / TDP-43 / RNA, 180 s
on-chip incubation). The full scan streamed roughly a thousand compositions in 51.3 minutes of instrument time and used
about 52 uL of protein; its droplets were held out as ground truth. A simulated rig then served droplets from that
scan for any composition the loop asked for, with the same per-setpoint costs the real instrument has (flow settling,
droplets per setpoint, the delay from pumps to camera). The loop's phase map was scored against the full scan's
boundary. The scan data itself is Transition Bio's and is not included here.

## What the loop needed

| | legacy raster | PhasePilot (Bayesian planner, stopping rule) |
|---|---|---|
| conditions | ~1000 | 68 setpoints |
| protein | 52 uL | 2.5 uL |
| instrument run time (pumps and camera busy) | 51.3 min | 2.9 min |
| wall clock | 51.3 min | 23 min |
| boundary accuracy vs the full scan | 1.0 (reference) | >= 0.997 |

The loop stops when the map changes by less than 1 % over two consecutive rounds.

**Protein: 20x less.** The loop only runs the conditions that pin the boundary.

**Instrument run time: 17x less.** 2.9 minutes of pumping and imaging instead of 51.

**Why wall clock is only 2x today.** The loop's 23 minutes were mostly waiting: each of its 7 rounds waited 180 s for
droplets to incubate on chip before the next decision, with the pumps idle. Keeping droplets flowing through that wait
(several setpoints in flight) brings the wall clock down toward the instrument time; with a 30 s incubation protocol
the simulation reaches about 10x on wall clock as well.

## Scaling with the number of variables

A raster costs k^n conditions for n variables at k levels. The loop samples the boundary, a surface of n-1
dimensions, so it costs about c k^(n-1), with c = 0.68 measured at n = 3. The ratio is therefore roughly constant in n,
which means a fixed saving buys extra dimensions: log_k(17) of them. At 10 levels per variable that is one more
variable in the same instrument time and protein; at 4 levels per variable it is two. Per-condition costs from the
replay give, at six variables, 36 instrument days for the raster against 2 for the loop
(`demo/render_scaling_linear.py`).

## Where Muse helps and where it does not

In the replay benchmark the Bayesian planner alone is the cheapest route to a 0.99 boundary. Language models were
better early (fewer than 20 settings) and worse when left to pick points by themselves, because they fixate on their
own priors. The design that worked, and the one that ran live, keeps the planner as the proposer and gives Muse the
decision: it reads the evidence, image quality and budget, chooses run / replicate / pause / finish, and explains the
choice. That makes every step auditable and lets Muse stop the run when the instrument misbehaves, which a planner
cannot see.

## The live run

On 4 November 2026 the loop ran on the Beta3 rig with G3BP1 / PolyA RNA / PEG. Muse chose every setpoint from the
live evidence and explained each one; SAM outlined every droplet; the setpoint queue checked every command before the
pumps moved. The footage in the film is from that run.
