@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
"C:\dev\venv\Scripts\python.exe" "C:\dev\scripts\transcribe\ata.py" %*
