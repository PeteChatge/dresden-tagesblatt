@echo off
cd /d "%~dp0"
python fetch.py
python fetch.py --export
pause
