@echo off
setlocal enabledelayedexpansion

set LOGFILE=taggui_setup.log
set SKIP_GIT=0
set CLEAR_CACHE=0
set CLEAN_OLD=0

echo Logging to %LOGFILE%
echo.

if not exist requirements.txt (
    echo ERROR: requirements.txt not found
    pause
    exit /b 1
)

where python >nul 2>nul
if !ERRORLEVEL! NEQ 0 (
    echo ERROR: Python not installed
    pause
    exit /b 1
)

echo Found Python

:: Parse command line arguments
if "%1"=="--skip-git" set SKIP_GIT=1
if "%1"=="--clear-cache" set CLEAR_CACHE=1
if "%1"=="--clean-old" set CLEAN_OLD=1

:: Check if git repo exists
if not exist .git goto no_git

if !SKIP_GIT! EQU 1 goto skip_git_flag

echo Pulling latest changes...
git pull
if errorlevel 1 goto git_failed
goto after_git

:git_failed
echo.
echo ======================================================
echo WARNING: Could not download latest updates
echo ======================================================
echo This usually means:
echo  - Your internet connection is offline
echo  - GitHub is temporarily unavailable
echo  - You have a network/firewall issue
echo.
echo You can still run TagGUI with your current version.
echo %date% %time% - Git pull failed > "%LOGFILE%"
echo.
set /p CONTINUE=Continue with setup? (Y/N):
if /i "!CONTINUE!"=="N" exit /b 1
echo OK, skipping update and continuing...
echo.

:skip_git_flag
echo Skipping git pull (--skip-git flag)
goto after_git

:no_git
echo Note: Not a git repository. Skipping git pull.
echo %date% %time% - No .git directory found > "%LOGFILE%"

:after_git

:: Check Python again (more thorough)
where python >nul 2>nul
if !ERRORLEVEL! NEQ 0 goto no_python

echo Python is installed
goto python_ok

:no_python
echo ERROR: Python not installed. Please install Python 3.10+
pause
exit /b 1

:python_ok

:: Check if requirements.txt exists
if not exist requirements.txt (
    echo ERROR: requirements.txt not found in current directory
    echo Make sure you are running this script from the TagGUI folder
    pause & exit /b 1
)

:: Check for venv in current directory
set VENV_PATH=venv
set VENV_EXISTS=0
if exist %VENV_PATH%\Scripts\activate.bat goto venv_found

:: Check parent directory
if exist ..\venv\Scripts\activate.bat (
    set VENV_PATH=..\venv
    set VENV_EXISTS=1
    echo Found virtual environment in parent directory
    goto venv_found
)

:: Create venv
echo Creating virtual environment...
python -m venv %VENV_PATH%
if errorlevel 1 (
    echo ERROR: Failed to create venv
    pause
    exit /b 1
)
goto venv_setup

:venv_found
set VENV_EXISTS=1

:venv_setup

echo Activating virtual environment...
call %VENV_PATH%\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)

:: Only install if venv was just created
if %VENV_EXISTS% EQU 0 (
    echo Upgrading pip...
    python -m pip install --upgrade pip > "%LOGFILE%" 2>&1

    echo Installing requirements...
    pip install -r requirements.txt > "%LOGFILE%" 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo.
        echo ======================================================
        echo ERROR: Failed to install dependencies
        echo ======================================================
        echo This usually means:
        echo  - Your internet connection is offline
        echo  - A Python package is not compatible with your system
        echo  - A package server is temporarily unavailable
        echo.
        echo Check the log file for details: %LOGFILE%
        echo.
        pause & exit /b 1
    )
    echo Dependencies installed successfully!
) else (
    echo Virtual environment already exists, skipping installation
)

:: Optional: Clear pip cache
if %CLEAR_CACHE% EQU 1 (
    echo Clearing pip cache...
    pip cache purge > "%LOGFILE%" 2>&1
    echo Cache cleared.
)

:: Optional: Clean old packages not in requirements.txt
if %CLEAN_OLD% EQU 1 (
    echo Cleaning old packages not in requirements.txt...
    pip list --format=freeze > current_packages.txt
    findstr /V /G:requirements.txt current_packages.txt > old_packages.txt
    if exist old_packages.txt (
        for /f %%i in (old_packages.txt) do (
            pip uninstall -y %%i > "%LOGFILE%" 2>&1
        )
        del old_packages.txt current_packages.txt
        echo Old packages removed.
    )
)

:: Run TagGUI
echo.
echo ======================================================
echo Starting TagGUI...
echo ======================================================
echo.
python taggui/run_gui.py
pause
