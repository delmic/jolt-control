setlocal
SET "scriptdir=%~dp0"
SET PYTHONPATH=%scriptdir%\..\src\;%PYTHONPATH%
python C:\development\jolt-control\install\windows\build.py
endlocal
