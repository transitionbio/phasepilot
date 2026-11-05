@echo off
REM worker_run.bat <stack> <out dir> <log dir>  - live analysis worker with SAM, output to <log dir>\worker.log
<rig>\live\liveworker.bat --stack "%~1" --out "%~2" --sam-checkpoint <rig>\live\model\sam\sam_vit_b_01ec64.pth --sam-every 4 --batch 2 --threads 8 --idle-exit 1800 > "%~3\worker.log" 2>&1
