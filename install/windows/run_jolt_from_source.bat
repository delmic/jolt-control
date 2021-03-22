setlocal
SET "scriptdir=%~dp0"
SET PYTHONPATH=%scriptdir%\..\src\;%PYTHONPATH%
REM Uncomment to run with the simulator
REM set TEST_NOHW=1
python %scriptdir%\..\src\jolt\gui\jolt_app.py
endlocal