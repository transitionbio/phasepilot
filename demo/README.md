# PhasePilot demo (replay of a recorded run)

Runs the whole closed loop locally on the recorded PhaseScan Beta3 run of 2026-10-28
(G3BP1 / PolyA RNA / PEG). Instrument and camera are replayed;
the live analysis worker (pipeline CNN + SAM), the Bayesian planner and Muse run for real.
No banner by default (demo_window --banner replay adds one); the PhasePilot tab draws the planner GP phase map
(log/map.json, written by loop/driver.py after every decision) under the measured points.

Files
- orchestrate.py   the loop: GUI queue code on simulated pumps, replay camera, live worker, driver, Muse summary
- demo_window.py   full-screen window: question dialog (beat 04), PhasePilot tab, Live analysis tab
- record_demo.sh   on-screen: recorder + orchestrator + window on DISPLAY :0 (writes runs/<stamp>/)
- record_offscreen.sh  no desktop needed: orchestrator + window that records itself (QT_QPA_PLATFORM=offscreen);
                   recording/phasepilot_replay_<stamp>.mp4 and .start (epoch of frame 0); closes 20 s after DONE
- build_edit.py    long edit: 12 storyboard beats with title cards (edit_cards.json) -> edit.json
- build_short.py   ~30 s edit: four moments, plain captions, no cards -> edit_short.json
- cut_demo.py      renders an edit list JSON into one MP4
- data/            frames_composition.csv (per-frame droplet composition from the pipeline barcode read-out),
                   fault_frames/ (empty channel, 2026-10-30, for the injected QC fault)
- assets/          NOT in git, ~600 MB. Rebuild with:
    (droplet CNN weights: internal Transition Bio model, not included)
    curl -L -o assets/sam_vit_b_01ec64.pth https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth
- ../live_demo/raw_pos0/   the 245 recorded frames (1.2 GB, .npy)   ../loop/.env   MUSE_API_KEY

Record:  ./record_demo.sh            (unattended; the dialog types the question and starts after 4 s)
         touch recording/STOP        when runs/<stamp>/DONE appears (or earlier)
Cut:     python cut_demo.py --raw recording/<mp4> --start <'start' epoch in record_*.log> \
             --decisions runs/<stamp>/log/decisions.jsonl --edit edit.json --out phasepilot_demo.mp4

Short cut (~30 s, phasepilot_30s.mp4):
    ./record_offscreen.sh                      # ~10 min; wait for runs/<stamp>/DONE and the window to exit
    python build_short.py --run runs/<stamp> --start $(cat recording/phasepilot_replay_<stamp>.mp4.start) --out edit_short.json
    ../.venv-gui/bin/python cut_demo.py --raw recording/phasepilot_replay_<stamp>.mp4 --start <same epoch> \
        --decisions runs/<stamp>/log/decisions.jsonl --edit edit_short.json --out phasepilot_30s.mp4

Transition Bio styled film (64 s, phasepilot_tbio.mp4): title; the real dashboard with panels numbered; SAM (the
worker's saved sam_frames played as video, render_sam_seq.py); Muse (dashboard with the panel boxed, then readable);
the loop (dashboard, then the planner's GP maps crossfaded through the run, render_map_anim.py); results slide
(20x protein, 2x time, +1 variable; raster k^n vs loop ~k^(n-1), tbio/scaling.png). Assets in tbio/ from the TBio deck.
    python render_map_anim.py --run runs/261104_0949 --out tbio/map_anim.mp4 --hold 0.8 --fade 1.4
    python render_sam_seq.py --run runs/261104_0949 --out tbio/sam_seq.mp4
    python build_tbio.py --raw recording/phasepilot_replay_261104_0949.mp4 --run runs/261104_0949 --out phasepilot_tbio.mp4

## Final 3-minute film (Muse hackathon panel)

`phasepilot_final.mp4` (188 s, 1920x1080, silent) built by `build_final.py`: TBio title; Will's light explainer
(`demo/source/phasepilot-the-problem.mp4`, not included) 0-22 s; Will's portrait phone footage of the Beta3 rig
(`live_rig_video.mp4` 15-44 s) framed over a blurred background with a TBio side panel; explainer 32-66 s
(dimensionality, Muse, SAM, sampling); phone footage of the live dashboard (2-12 s); our dashboard/SAM/Muse/map
beats (`phasepilot_tbio.mp4` 3-52 s); results card; explainer 72-87 s (closing); TBio end card. Segments fade
through white (this ffmpeg has no xfade).
Results card (build_final.py results_card2 + render_scaling.py -> tbio/scaling2.png): 20x less protein (2.5 vs 52 uL),
17x less instrument run time (2.9 vs 51 min of pumping/imaging; wall clock 23 min because each of 7 rounds waits 180 s
incubation), +1 variable in the same time and protein at 10 levels per variable (+2 at 4 levels: log_k(17)). Numbers
from runs/lab_wait_imp_both2s (bayes_misclass, wait mode, transit, stopping rule). Pacing: explainer x1.25 (intro) and x1.15,
rig footage 9 s per beat, SAM beat x0.85, Muse and map beats x1.0, closing explainer only "one closed loop"; 180 s total.

## Muse-directed cut (phasepilot_muse.mp4, 180 s)

`muse_director.py` sends Muse Wonder (Meta Model API, model muse-wonder-1.0, key in loop/.env, reasoning_effort=medium)
the film's content, footage inventory, measured numbers, TBio style rules and the presenters' pacing feedback, and gets
back a JSON beat plan (muse/plan.json, with a presenter line per beat). `build_muse.py` renders the plan with the same
segment functions as build_final.py; a card's image_prompt is sent to muse-image-1.0 (art cached in muse/art/).
    python muse_director.py --out muse/plan.json
    python build_muse.py --plan muse/plan.json --out phasepilot_muse.mp4

## Muse-built cut, all slides in the TBio template (phasepilot_muse3.mp4, 180 s)

Will's explainer beats are remade as animated Transition Bio slides (tbio_anim.py: white page, logo top-left, blue
heading, lines fading in at given times, one animated diagram on the right from the primitives cell / demix /
phase_diagram / droplet / kn_curve / loop / sam / sampling / nodes / applications). muse_director2.py gives Muse Wonder
the primitives, the footage inventory, the numbers and the style rules; Muse writes every slide (copy, line timings,
diagram, durations, presenter line) as muse/plan3.json; build_muse.py renders it (anim, phone, loop, results_stats,
results_chart, title, end). Will's feedback folded in: linear scaling chart (render_scaling_linear.py -> tbio/scaling3.png,
36 days vs 2 days at six variables), results on two slides with the numbers revealed one at a time, no wall-clock
detail, closing animation into the application space.
    python muse_director2.py --out muse/plan3.json
    python build_muse.py --plan muse/plan3.json --out phasepilot_muse3.mp4

## v2 hand cut on Will's dark explainer (phasepilot_final2.mp4, 180 s) -- current best

build_final2.py: the phasepilot_final.mp4 structure, but Will's content comes from phasepilot-the-problem_dark.mp4
(fuller: formula line, "we can do better", photo tiles), re-styled without touching the animations: negate + hue=180
inverts lightness and keeps hues, colorlevels pushes the background to white, the frame is scaled to 88 % on a white
page with the logo top-left. Will's notes: results on two slides (numbers revealed one at a time, no wall-clock
detail), linear chart with large labels, closing = biology-is-high-dimensional animation fading into the application
space. Dark source beats used: 0-23, 29-67.7, 75-89.5.
    python build_final2.py --out phasepilot_final2.mp4
Final (11-04 23:30): the real-time phase map gets its own full-width beat after the dashboard shot (tbio/map_anim.mp4 at
1360 px with a side panel, 15.8 s; the old reduced map panel beat is dropped). 180.1 s.

## Voiced cut (phasepilot_voiced.mp4, 4:01) -- the film conformed to the recorded narration

build_voiced.py: OBS take (~/snap/obs-studio/common/2026-11-04 23-49-38.mp4, 4:02) transcribed locally with vosk
(small en-us model in the scratchpad) to get word times; each narration block's start is an anchor (dict A in the
script, hand-corrected for 'readout' and 'chart'); every beat of phasepilot_final2 is retimed to start on its anchor
(animations up to 1.3x slower then frozen on the last frame, phone footage runs longer, stills hold); the take's audio
is muxed in untouched; the presenter appears in a 420x236 box bottom-right during the intro (0-12.6 s) and from
"and that's PhasePilot" (237.6 s) to the end.
    python build_voiced.py --take "<obs mp4>" --out phasepilot_voiced.mp4
3-minute voiced version (11-05 00:16): edit_take.py drops the pause after "Hi" (0.3-3.0 s), caps every pause > 0.5 s to
0.35 s (66 cuts, 43 s) and speeds the take up x1.103 (atempo, pitch kept) -> take_edit.mp4 2:59.97 with remapped
anchors; build_voiced.py --anchors anchors_edit.json -> phasepilot_voiced.mp4 (2:59.7).
Transitions fixed (11-05 00:40): the white fades are gone; every join is a 0.5 s cross-dissolve rendered inside the
first 0.5 s of the incoming beat (old slide's last frame held underneath), so cue times are unchanged; dark-explainer
slices now stop 0.25 s before the next beat so a frozen frame never shows the following slide; the final concat is
re-encoded (no -c copy) with a global fade in/out. build_voiced.py --music <mp3> --music_db -20 adds a looped bed
ducked under the voice (sidechaincompress), fading in over the title and out over the end card.
Music version (11-05 00:47): phasepilot_voiced_music.mp4 = the same film with a bed: "Fluidscape" by Kevin MacLeod,
incompetech.com, CC BY 4.0 (commercial use allowed with credit; credit line drawn on the end card). File kept at
tbio/Fluidscape_KevinMacLeod_CCBY40.mp3. Mixed at --music_db -14 (user: 20 % quieter than -12) with sidechain ducking (ratio 4): bed sits 14-17 dB
under the voice (-36..-39 dB vs voice -24 dB mean), fades in over 2 s, out over the last 3 s.
