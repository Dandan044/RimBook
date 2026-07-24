@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting RimBook...
echo [1/2] Rebuilding frontend (usually 1-2 min, please wait)...
echo [2/2] Killing old instances and launching server...
python -c "from rimbook.web.launcher import restart_server; r=restart_server(); print('RimBook running at ' + r['url'] + '  (pid=' + str(r['pid']) + ')')"
if errorlevel 1 (
  echo.
  echo FAILED. If rebuild failed, check that Node.js/npm is installed.
  pause
  exit /b 1
)
pause
