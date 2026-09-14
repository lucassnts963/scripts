@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

set "PYTHON_EXE=C:\dev\venv\Scripts\python.exe"
set "SCRIPT_PY=C:\dev\scripts\transcribe\transcribe.py"

:: Captura o arquivo com aspas preservadas
set "AUDIO_FILE=%~1"

:: Coleta apenas os argumentos subsequentes preservando as aspas
set "EXTRA_ARGS="
:loop_args
shift
if "%~1"=="" goto run_python
set EXTRA_ARGS=%EXTRA_ARGS% %1
goto loop_args

:run_python
"%PYTHON_EXE%" "%SCRIPT_PY%" "%AUDIO_FILE%" %EXTRA_ARGS%

echo.
pause
