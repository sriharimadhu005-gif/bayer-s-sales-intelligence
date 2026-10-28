@echo off
echo ===================================================
echo Starting Bayer Sales Intelligence Unified Server...
echo ===================================================

cd /d "%~dp0"

REM If frontend/dist doesn't exist, build it
if not exist "frontend\dist\index.html" (
    echo Building frontend static assets...
    cd frontend
    call npm run build
    cd ..
)

echo.
echo ===================================================
echo Entire Working Project is available at:
echo   http://localhost:8000
echo.
echo Swagger API Documentation:
echo   http://localhost:8000/docs
echo ===================================================
echo.

cd backend
call .\venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
