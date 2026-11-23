@echo off
setlocal
cd /d "%~dp0"
echo === Isolated multi-instance concurrency demo ===
echo Uses separate Compose project pm_concurrency, DB port 5434, API ports 8010/8011.
docker compose -p pm_concurrency -f compose.yaml -f compose.concurrency.yaml up -d --build api api2
if errorlevel 1 goto failed

echo Waiting for both API health checks...
set /a attempts=0
:health
set /a attempts+=1
curl --fail --silent --output NUL http://127.0.0.1:8010/health
if errorlevel 1 goto wait
curl --fail --silent --output NUL http://127.0.0.1:8011/health
if not errorlevel 1 goto run
:wait
if %attempts% GEQ 30 goto failed
timeout /t 2 /nobreak >NUL
goto health

:run
echo Both API instances healthy.
python -m scripts.multi_instance_test
if errorlevel 1 goto failed
echo.
echo DEMONSTRATION PASSED
exit /b 0

:failed
echo.
echo DEMONSTRATION FAILED. Inspect: docker compose -p pm_concurrency -f compose.yaml -f compose.concurrency.yaml ps -a
exit /b 1
