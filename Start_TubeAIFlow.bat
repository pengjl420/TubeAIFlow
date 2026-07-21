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

where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm was not found on PATH.
  echo Please install Node.js and try again.
  pause
  exit /b 1
)

set "BACKEND_PYTHON=%BACKEND_DIR%\.venv\Scripts\python.exe"

if not exist "%BACKEND_PYTHON%" (
  set "BOOTSTRAP_PYTHON="
  where py.exe >nul 2>nul
  if not errorlevel 1 set "BOOTSTRAP_PYTHON=py -3.12"
  if not defined BOOTSTRAP_PYTHON (
    where python.exe >nul 2>nul
    if not errorlevel 1 set "BOOTSTRAP_PYTHON=python"
  )
  if not defined BOOTSTRAP_PYTHON (
    echo [ERROR] The backend environment does not exist and Python 3.12 was not found.
    echo Install Python 3.12, then run this launcher again.
    pause
    exit /b 1
  )
  echo Creating backend virtual environment...
  %BOOTSTRAP_PYTHON% -m venv "%BACKEND_DIR%\.venv"
  if errorlevel 1 (
    echo [ERROR] Failed to create backend virtual environment.
    pause
    exit /b 1
  )
)

"%BACKEND_PYTHON%" --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] The existing backend virtual environment is damaged.
  echo Recreate "%BACKEND_DIR%\.venv" with Python 3.12.
  pause
  exit /b 1
)

echo Installing backend dependencies if needed...
pushd "%BACKEND_DIR%" >nul
"%BACKEND_PYTHON%" -m pip install -r requirements.txt
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
  call npm.cmd install
  if errorlevel 1 (
    popd >nul
    echo [ERROR] Failed to install frontend dependencies.
    pause
    exit /b 1
  )
  popd >nul
)

pushd "%BACKEND_DIR%" >nul
for /f %%P in ('""%BACKEND_PYTHON%" -m app.find_available_port"') do set "BACKEND_PORT=%%P"
popd >nul
if not defined BACKEND_PORT (
  echo [ERROR] No available backend port was found.
  pause
  exit /b 1
)
set "APP_PORT_OVERRIDE=%BACKEND_PORT%"
set "VITE_API_PORT=%BACKEND_PORT%"

if /I "%~1"=="--check" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\Start_TubeAIFlowServices.ps1" -BackendPort "%BACKEND_PORT%" -Check
  if errorlevel 1 exit /b 1
  echo [OK] Backend Python, dependencies, Node.js, npm, port selection, and background launcher are ready.
  exit /b 0
)

echo.
echo Starting backend on http://127.0.0.1:%BACKEND_PORT% ...
echo Starting frontend: http://127.0.0.1:5173
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\Start_TubeAIFlowServices.ps1" -BackendPort "%BACKEND_PORT%"
if errorlevel 1 (
  echo [ERROR] Failed to start TubeAIFlow services.
  pause
  exit /b 1
)

echo.
echo TubeAIFlow is starting.
echo Open http://127.0.0.1:5173 in your browser.
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5173"
exit /b 0
