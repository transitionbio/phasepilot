@echo off
REM PhasePilot live run on Beta3 (G3BP1 / PolyA RNA / PEG), same pumps and stocks as the 261028 run.
REM   launch_live.bat <acquisition ome.tif> <run name> [budget_uL] [reserve_uL]
REM Starts the live analysis worker on the growing acquisition and the loop driver (planner -> Muse -> queue).
REM The GUI must already be running Cont Screen from the loop config (setpoint_queue_4D = <rig>\queue).
if "%~2"=="" ( echo usage: launch_live.bat ^<acquisition ome.tif^> ^<run name^> [budget_uL] [reserve_uL] & exit /b 1 )
set STACK=%~1
set NAME=%~2
set BUDGET=%~3
if "%BUDGET%"=="" set BUDGET=30
set RESERVE=%~4
if "%RESERVE%"=="" set RESERVE=3
set OUT=<rig>\live\out_%NAME%
set LOG=<rig>\loop_log\%NAME%
mkdir "%OUT%" 2>nul
mkdir "%LOG%" 2>nul
echo worker: %STACK% -> %OUT%
start "liveworker %NAME%" /min <rig>\loop\worker_run.bat "%STACK%" "%OUT%" "%LOG%"
echo driver: budget %BUDGET% uL, reserve %RESERVE% uL -> %LOG%
cd /d <rig>\loop
<rig>\envs\live\python.exe driver.py --worker-out "%OUT%" --queue <rig>\queue --log "%LOG%" ^
  --budget %BUDGET% --reserve %RESERVE% --hold 60 --settle 20 --lag 165 --depth 1 --warm 4 --candidates 5 ^
  --min-droplets 20 --qc-window 60 --qc-stall 240 --qc-max-sam-reject 0.5 ^
  --question @<rig>\loop\question_g3bp1.txt ^
  > "%LOG%\driver.log" 2>&1
echo driver exited; see %LOG%\driver.log
