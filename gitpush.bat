@echo off
cd /d "%~dp0"
git add .
if "%~1"=="" (
  git commit -m "update %date% %time%"
) else (
  git commit -m "%*"
)
git push
pause
