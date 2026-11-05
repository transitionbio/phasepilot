# PhasePilot

**An agent in the loop of a real phase-separation experiment.** Meta's Muse chooses the next condition on a
PhaseScan microfluidic rig, Segment Anything checks every droplet image before a result counts, and a Bayesian
planner keeps the phase map. Built by Transition Bio for the Muse hackathon, November 2026.

[Watch the 3-minute demo](media/phasepilot_demo.mp4)

## The problem

Proteins condense by phase separation, and every protein has its own multidimensional phase diagram. PhaseScan
maps those diagrams in 100-picolitre microfluidic droplets, one condition per droplet, about a million times less
protein per data point than plate-based labware. But a comprehensive scan costs k^n conditions for n variables at k
levels, so past four or five variables it becomes impossible, and that is for a single protein.

PhasePilot replaces the raster with a loop that only samples where the boundary is.

## How the loop works

```
            question, limits, protein budget
                          |
   +-------------------- Muse (muse-spark-1.3) ---------------------+
   |   reads the evidence, picks ONE action, writes down why        |
   |   run_candidate <rank> | replicate <id> | pause | finish       |
   +---------------------------+-----------------------------------+
                               | setpoint (pump flows)
                   instrument controller checks limits
                               |
                    PhaseScan rig (syringe pumps, chip, camera)
                               |  droplet images, ~3 min later
                     live worker: CNN classifies each droplet
                                 SAM outlines each droplet (QC)
                               |  results that passed QC
                 Bayesian planner (GP on phase fraction)
                 ranks candidate conditions by P(map is wrong there)
                               |
                               +----> back to Muse
```

**Muse** (`loop/muse.py`, `loop/driver.py`). Each round the driver assembles the evidence: the question, the
results so far (composition, droplets counted, phase-separated fraction), what is in flight, the image-QC line from
SAM, the protein budget, and the planner's ranked candidates. Muse replies in JSON with its reasoning, an observation,
one action and a rationale. It can only choose among four actions; it never sets flows directly, and the instrument
controller checks every setpoint before the pumps move. If the call fails or the reply is not a valid action, the
driver falls back to the planner's top candidate and records that the fallback, not Muse, decided. Every decision,
prompt and reply is logged to `decisions.jsonl` and shown on the dashboard. See `examples/replay_run/decisions.jsonl`
for a complete run.

**SAM** (`live/live_worker.py`). The live worker reads frames from the growing acquisition as the camera writes
them. A CNN classifies each droplet mixed or phase separated; Segment Anything (ViT-B) then outlines every droplet the
detector found and rejects partial or malformed ones. A result only counts when the image passes; if the channel
empties, SAM rejects everything and the loop pauses rather than spend protein on bad images. SAM does not classify
phase separation; it is the quality gate.

**Planner** (`loop/planner.py`). A Gaussian process on the phase-separated fraction over the composition space.
Candidates are ranked by the probability that the current map is wrong there, which concentrates sampling on the
boundary, a surface of n-1 dimensions. Each new result redraws the map and the predicted boundary.

**Instrument side** (`loop/setpoint_queue.py`). The rig's control software polls a folder of setpoint files. The
driver writes one JSON file per setpoint; the controller validates it against the instrument limits, runs it for the
hold time, and records accept / reject / done / cancel with timestamps so every observation traces to the setpoint
that produced it. This is the only way the agent touches the hardware.

**Dashboard** (`dashboard/phasepilot_tab.py`). A PyQt window showing every decision and who made it, Muse's reasoning
for the selected decision, SAM's droplet outlines (green accepted, red rejected) with the reject rate over time, and
the results with the phase map and predicted boundary.

## What it changes

Measured on a three-variable replay (G3BP1 / TDP-43 / RNA, 180 s incubation), matching the full scan's boundary
to an accuracy of 0.997 or better:

| | legacy raster | PhasePilot |
|---|---|---|
| protein | 52 uL | 2.5 uL (**20x less**) |
| instrument run time (pumps and camera busy) | 51 min | 2.9 min (**17x less**) |

A raster costs k^n conditions; the loop samples the boundary, about k^(n-1). So the same instrument time and protein
buy one more variable at 10 levels per variable, or two more at 4 levels. Details and caveats in
[docs/results.md](docs/results.md).

On 4 November 2026 the loop ran live on the Beta3 rig with G3BP1 / PolyA RNA / PEG, Muse choosing each setpoint from
the live evidence; the phone footage in the film is from that run.

## Repository

| path | what |
|---|---|
| `loop/` | the loop: `driver.py` (planner -> Muse -> queue), `muse.py` (Muse client and prompt), `planner.py` (GP), `setpoint_queue.py` (instrument interface), tests, the Muse brief used on the day |
| `live/` | `live_worker.py`: the live analysis worker with the SAM quality gate |
| `dashboard/` | `phasepilot_tab.py`: the PhasePilot dashboard (standalone PyQt window or a tab in the rig GUI) |
| `examples/replay_run/` | a complete logged run: every Muse prompt and reply, results, and the phase map after each decision |
| `demo/` | the film pipeline: Transition Bio slide renderer, Muse Wonder as film director, voiceover conform, music mix |
| `media/` | the 3-minute hackathon film |
| `docs/` | results and method |

## Running it

Requirements: Python 3.8+, `pip install -r requirements.txt`. For SAM, download the ViT-B checkpoint from
https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth. Muse is reached through Meta's Model API: copy
`loop/.env.example` to `loop/.env` and set `MUSE_API_KEY`. Never commit `.env`.

Simulated loop (no instrument), which exercises Muse, the planner and the queue end to end:

    cd loop && python test_loop.py

On an instrument, the control software must run its continuous screen from a setpoint queue folder; the live worker
runs on the growing acquisition; the driver runs the loop:

    python live/live_worker.py --stack <acquisition.ome.tif> --out <worker_out> --sam-checkpoint sam_vit_b_01ec64.pth --sam-every 4
    python loop/driver.py --worker-out <worker_out> --queue <rig>/queue --log <run_log> --budget 26 --reserve 3 \
        --hold 60 --settle 20 --lag 165 --question @loop/question_g3bp1.txt
    python dashboard/phasepilot_tab.py --log <run_log>

`live_worker.py` depends on Transition Bio's droplet detection and classification package (`phasescan`), which is not
part of this repository; the SAM gate and everything in `loop/` and `dashboard/` are self-contained.

## The film

`demo/` holds everything that made the film: the Transition Bio slide renderer (`tbio_anim.py`), the cut on Will
Arter's explainer animation re-styled to the template without touching the animation (`build_final2.py`), Muse Wonder
directing a cut from a brief (`muse_director2.py`, `build_muse.py`), the conform of the picture to the recorded
voiceover using local word timings (`edit_take.py`, `build_voiced.py`), and the ducked music mix. Source footage and
the music file are not included; see `demo/README.md`.

## Licence and credits

Code: Apache License 2.0, Copyright 2026 Transition Bio Ltd. See `LICENSE` and `NOTICE`.

Segment Anything is by Meta AI Research (Apache 2.0). Muse and Muse Wonder are Meta models reached through the Meta
Model API under its terms. The film's music is "Fluidscape" by Kevin MacLeod (incompetech.com), Creative Commons
Attribution 4.0. The explainer animation is by Will Arter, Transition Bio.
