@echo off
setlocal
title RentReady Vision

cd /d "%~dp0"

echo.
echo ==========================================
echo        Starting RentReady Vision
echo ==========================================
echo.

REM Find Python
where python >nul 2>&1
if %errorlevel%==0 (
    set "PYEXE=python"
) else (
    where py >nul 2>&1
    if %errorlevel%==0 (
        set "PYEXE=py"
    ) else (
        echo ERROR: Python was not found.
        echo Install Python, then run this file again.
        pause
        exit /b 1
    )
)

REM Create virtual environment on first run
if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    %PYEXE% -m venv .venv
    if errorlevel 1 goto :error

    echo Installing dependencies...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :error
)

REM Create .env from template on first run
if not exist ".env" (
    if exist ".env.example" (
        copy /Y ".env.example" ".env" >nul
        echo Created .env from .env.example
    )
)

echo Checking AWS resources...
".venv\Scripts\python.exe" scripts\setup_aws.py
if errorlevel 1 goto :error
echo.

echo Starting server at http://localhost:8000
echo Close this window or press Ctrl+C to stop RentReady Vision.
echo.

REM Open browser shortly after server starts
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000"

".venv\Scripts\python.exe" -m uvicorn app.main:app --env-file .env --host 127.0.0.1 --port 8000 --reload
goto :end

:error
echo.
echo RentReady Vision could not start.
pause

:end
endlocal
