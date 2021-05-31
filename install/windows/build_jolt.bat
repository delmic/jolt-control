setlocal
SET "scriptdir=%~dp0"
SET PYTHONPATH=%scriptdir%\..\..\src\;%PYTHONPATH%
python %scriptdir%\build.py
endlocal
