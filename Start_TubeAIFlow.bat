@echo off
setlocal

set "ROOT=%~dp0"
set "BACKEND_DIR=%ROOT%backend"
set "FRONTEND_DIR=%ROOT%frontend"

title TubeAIFlow Launcher

echo.
echo ========================================
echo  TubeAIFlow - Start
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python was not found on PATH.
  echo Please install Python 3.10+ and try again.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm was not found on PATH.
  echo Please install Node.js and try again.
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\.venv\Scripts\python.exe" (
  echo Creating backend virtual environment...
  python -m venv "%BACKEND_DIR%\.venv"
  if errorlevel 1 (
    echo [ERROR] Failed to create backend virtual environment.
    pause
    exit /b 1
  )
)

echo Installing backend dependencies if needed...
pushd "%BACKEND_DIR%" >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  popd >nul
  echo [ERROR] Failed to install backend dependencies.
  pause
  exit /b 1
)
popd >nul

if not exist "%FRONTEND_DIR%\node_modules" (
  echo Installing frontend dependencies...
  pushd "%FRONTEND_DIR%" >nul
  call npm install
  if errorlevel 1 (
    popd >nul
    echo [ERROR] Failed to install frontend dependencies.
    pause
    exit /b 1
  )
  popd >nul
)

pushd "%BACKEND_DIR%" >nul
for /f %%P in ('.venv\Scripts\python.exe -m app.find_available_port') do set "BACKEND_PORT=%%P"
popd >nul
if not defined BACKEND_PORT (
  echo [ERROR] No available backend port was found.
  pause
  exit /b 1
)
set "APP_PORT_OVERRIDE=%BACKEND_PORT%"
set "VITE_API_PORT=%BACKEND_PORT%"

echo.
echo Starting backend on http://127.0.0.1:%BACKEND_PORT% ...
start "TubeAIFlow Backend" cmd /k "cd /d "%BACKEND_DIR%" && .venv\Scripts\python.exe -m app.run"

echo Starting frontend: http://127.0.0.1:5173
start "TubeAIFlow Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev"

echo.
echo TubeAIFlow is starting.
echo Open http://127.0.0.1:5173 in your browser.
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5173"
echo.
pause
