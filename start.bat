@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting RimBook server (killing any existing instance first)...
python -c "from rimbook.web.launcher import start_server; r=start_server(force_restart=True); print('RimBook running at ' + r['url'] + '  (pid=' + str(r['pid']) + ')')"
pause
