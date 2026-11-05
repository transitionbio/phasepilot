#!/bin/bash
# Record the PhasePilot replay demo WITHOUT the desktop: the demo window renders offscreen and records itself.
#   ./record_offscreen.sh [run dir] [fault setpoint id] [auto seconds]
# Writes <run dir>/log/... (orchestrator), recording/phasepilot_replay_<stamp>.mp4 (+ .start = epoch of frame 0).
# The window closes itself 20 s after the orchestrator writes <run dir>/DONE.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
STAMP=$(date +%y%m%d_%H%M)
RUN=${1:-$HERE/runs/$STAMP}
FAULT=${2:-C06}
AUTO=${3:-4}
REC="$HERE/recording"
mkdir -p "$REC" "$RUN/log"

PYTHONNOUSERSITE=1 nohup "$HOME/anaconda3/envs/phasescan-cloud/bin/python" "$HERE/orchestrate.py" \
    --run-dir "$RUN" --fault "$FAULT" > "$RUN/orchestrate.log" 2>&1 &
echo "orchestrator pid $!  (waits for the question)"

QT_QPA_PLATFORM=offscreen nohup "$HOME/phasescan-closed-loop/.venv-gui/bin/python" "$HERE/demo_window.py" \
    --run-dir "$RUN" --cycle 60:25 --auto "$AUTO" --record "$REC/phasepilot_replay_$STAMP.mp4" > "$RUN/window.log" 2>&1 &
echo "window pid $!  -> $REC/phasepilot_replay_$STAMP.mp4"
echo "run dir $RUN"
