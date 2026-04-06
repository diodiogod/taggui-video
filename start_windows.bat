@echo off
chcp 65001 >nul
cls
echo.
echo.
echo          █████████╗  █████╗    ██████╗    ██████╗   ██╗   ██╗  ██╗
echo          ╚═══██╔══╝ ██╔══██╗  ██╔════╝   ██╔════╝   ██║   ██║  ██║╗
echo              ██║║   ███████║  ██║  ███╗  ██║  ███╗  ██║   ██║  ██║║
echo              ██║║   ██╔══██║╗ ██║   ██║  ██║   ██║  ██║   ██║  ██║║
echo              ██║║   ██║╗ ██║║ ╚██████╔╝  ╚██████╔╝  ╚██████╔╝  ██║║
echo              ╚═╝║   ╚═╝║  ╚═╝║ ╚═════╝║   ╚═════╝║   ╚═════╝║  ╚═╝╝
echo               ╚═╝    ╚═╝  ╚═╝    ╚════╝     ╚════╝     ╚════╝   ╚═╝
echo                        ██╗   ██╗██╗██████╗ ███████╗ ██████╗
echo                        ██║   ██║██║██╔══██╗██╔════╝██╔═══██╗
echo                        ██║   ██║██║██║  ██║█████╗  ██║   ██║
echo                        ╚██╗ ██╔╝██║██║  ██║██╔══╝  ██║   ██║
echo                         ╚████╔╝ ██║██████╔╝███████╗╚██████╔╝
echo                          ╚═══╝  ╚═╝╚═════╝ ╚══════╝ ╚═════╝
echo                           ╚══╝   ╚══╝╚════╝  ╚═════╝  ╚════╝
echo.
echo                             ██╗       ███╗   ███╗
echo                            ███║       ████╗ ████║
echo                            ╚██║       ██╔████╔██║
echo                             ██║       ██║╚██╔╝██║
echo                             ██║       ██║ ╚═╝ ██║
echo                             ╚═╝       ╚═╝     ╚═╝
echo.
echo.
setlocal enabledelayedexpansion

set LOGFILE=taggui_setup.log
set SKIP_GIT=0
set CLEAR_CACHE=0
set CLEAN_OLD=0
set REFRESH_TORCH=0
set ENABLE_CRASH_DIAG=0
set CUDA_OVERRIDE=
set TORCH_VERSION=2.7.1
set TORCHVISION_VERSION=0.22.1

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
for %%A in (%*) do (
    if /I "%%~A"=="--skip-git" set SKIP_GIT=1
    if /I "%%~A"=="--clear-cache" set CLEAR_CACHE=1
    if /I "%%~A"=="--clean-old" set CLEAN_OLD=1
    if /I "%%~A"=="--refresh-torch" set REFRESH_TORCH=1
    if /I "%%~A"=="--crash-log" set ENABLE_CRASH_DIAG=1
    if /I "%%~A"=="--no-crash-log" set ENABLE_CRASH_DIAG=0
    set ARG=%%~A
    if /I "!ARG:~0,7!"=="--cuda=" set CUDA_OVERRIDE=!ARG:~7!
)

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

set SHOULD_INSTALL=0
set SHOULD_INSTALL_REQUIREMENTS=0
set SHOULD_REFRESH_TORCH=0
set SHOULD_INSTALL_TORCH=0
set REQ_FINGERPRINT_FILE=%VENV_PATH%\.requirements.sha256
set CURRENT_REQUIREMENTS_HASH=
set INSTALLED_REQUIREMENTS_HASH=

for /f "usebackq delims=" %%H in (`python -c "import hashlib, pathlib; print(hashlib.sha256(pathlib.Path('requirements.txt').read_bytes()).hexdigest())"`) do (
    if not defined CURRENT_REQUIREMENTS_HASH set "CURRENT_REQUIREMENTS_HASH=%%H"
)

if exist "%REQ_FINGERPRINT_FILE%" (
    set /p INSTALLED_REQUIREMENTS_HASH=<"%REQ_FINGERPRINT_FILE%"
)

if %VENV_EXISTS% EQU 0 (
    set SHOULD_INSTALL=1
    set SHOULD_INSTALL_TORCH=1
    set SHOULD_INSTALL_REQUIREMENTS=1
) else if %REFRESH_TORCH% EQU 1 (
    set SHOULD_INSTALL=1
    set SHOULD_REFRESH_TORCH=1
    set SHOULD_INSTALL_TORCH=1
)

if /I not "%CURRENT_REQUIREMENTS_HASH%"=="%INSTALLED_REQUIREMENTS_HASH%" (
    set SHOULD_INSTALL=1
    set SHOULD_INSTALL_REQUIREMENTS=1
)

:: Install only when the venv is new, requirements changed, or the user refreshed Torch
if %SHOULD_INSTALL% EQU 1 (
    echo Upgrading pip...
    python -m pip install --upgrade pip > "%LOGFILE%" 2>&1
	
    if !SHOULD_INSTALL_TORCH! EQU 1 (
        set CUDA_VERSION=cpu
        set DRIVER_VERSION=
        if defined CUDA_OVERRIDE (
            if /I "!CUDA_OVERRIDE!"=="auto" (
                set CUDA_OVERRIDE=
            ) else if /I "!CUDA_OVERRIDE!"=="cpu" (
                set CUDA_VERSION=cpu
            ) else if /I "!CUDA_OVERRIDE!"=="cu118" (
                set CUDA_VERSION=cu118
            ) else if /I "!CUDA_OVERRIDE!"=="cu126" (
                set CUDA_VERSION=cu126
            ) else if /I "!CUDA_OVERRIDE!"=="cu128" (
                set CUDA_VERSION=cu128
            ) else (
                echo ERROR: Unsupported CUDA override "!CUDA_OVERRIDE!"
                echo Supported values: cpu, cu118, cu126, cu128, auto
                pause
                exit /b 1
            )
        )

        if defined CUDA_OVERRIDE (
            echo Using manual CUDA override: !CUDA_VERSION!
        ) else (
            echo Detecting CUDA version...
            nvidia-smi >nul 2>&1
            if !ERRORLEVEL! EQU 0 (
                for /f "usebackq tokens=1 delims=, " %%i in (`nvidia-smi --query-gpu=driver_version --format=csv,noheader,nounits 2^>nul`) do (
                    if not defined DRIVER_VERSION set "DRIVER_VERSION=%%i"
                )
                if not defined DRIVER_VERSION (
                    for /f "usebackq tokens=1 delims=, " %%i in (`nvidia-smi --query-gpu=driver_version --format=csv,noheader 2^>nul`) do (
                        if not defined DRIVER_VERSION set "DRIVER_VERSION=%%i"
                    )
                )
                if not defined DRIVER_VERSION (
                    for /f "tokens=6 delims= " %%i in ('nvidia-smi 2^>nul ^| findstr /C:"Driver Version"') do (
                        if not defined DRIVER_VERSION set "DRIVER_VERSION=%%i"
                    )
                )
                if defined DRIVER_VERSION (
                    echo !DRIVER_VERSION!| findstr /R "^[0-9][0-9]*\.[0-9][0-9]*$" >nul 2>&1
                    if !ERRORLEVEL! NEQ 0 (
                        set DRIVER_VERSION=
                    )
                )
                if defined DRIVER_VERSION (
                    echo Found NVIDIA GPU with driver: !DRIVER_VERSION!
                ) else (
                    echo WARNING: Could not parse NVIDIA driver version, defaulting to CPU Torch stack
                    echo If you know the correct wheel channel, rerun with --cuda=cu128 ^(or cu126 / cu118^)
                )

                :: Detect CUDA wheel channel from driver
                if defined DRIVER_VERSION (
                    for /f "tokens=1 delims=." %%v in ("!DRIVER_VERSION!") do (
                        if %%v GEQ 570 (
                            set CUDA_VERSION=cu128
                            echo Detected CUDA 12.8-capable driver
                        ) else if %%v GEQ 560 (
                            set CUDA_VERSION=cu126
                            echo Detected CUDA 12.6-capable driver
                        ) else if %%v GEQ 450 (
                            set CUDA_VERSION=cu118
                            echo Detected CUDA 11.8-capable driver
                        )
                    )
                )
            ) else (
                echo No NVIDIA GPU detected, installing CPU-only PyTorch
                echo If this machine does have an NVIDIA GPU, rerun with --cuda=cu128 ^(or cu126 / cu118^)
            )
        )

        if !SHOULD_REFRESH_TORCH! EQU 1 (
            echo Refreshing Torch stack in existing virtual environment...
            pip uninstall -y torch torchvision torchaudio xformers flash-attn > "%LOGFILE%" 2>&1
        )

        echo Installing PyTorch !TORCH_VERSION! / torchvision !TORCHVISION_VERSION! for !CUDA_VERSION!...
        if "!CUDA_VERSION!"=="cpu" (
            pip install --upgrade --force-reinstall torch==!TORCH_VERSION! torchvision==!TORCHVISION_VERSION! --index-url https://download.pytorch.org/whl/cpu >> "%LOGFILE%" 2>&1
        ) else if "!CUDA_VERSION!"=="cu118" (
            pip install --upgrade --force-reinstall torch==!TORCH_VERSION! torchvision==!TORCHVISION_VERSION! --index-url https://download.pytorch.org/whl/cu118 >> "%LOGFILE%" 2>&1
        ) else if "!CUDA_VERSION!"=="cu126" (
            pip install --upgrade --force-reinstall torch==!TORCH_VERSION! torchvision==!TORCHVISION_VERSION! --index-url https://download.pytorch.org/whl/cu126 >> "%LOGFILE%" 2>&1
        ) else if "!CUDA_VERSION!"=="cu128" (
            pip install --upgrade --force-reinstall torch==!TORCH_VERSION! torchvision==!TORCHVISION_VERSION! --index-url https://download.pytorch.org/whl/cu128 >> "%LOGFILE%" 2>&1
        )

        if !ERRORLEVEL! NEQ 0 (
            echo ERROR: Failed to install PyTorch
            echo Check the log file for details: %LOGFILE%
            pause & exit /b 1
        )
        echo PyTorch installed successfully!

        :: Flash-attention wheels have historically been tightly coupled to specific Torch builds.
        :: Keep this optional and avoid pinning old wheel URLs during refreshes.
        if not "!CUDA_VERSION!"=="cpu" (
            echo Skipping flash-attention wheel install on Windows ^(optional^).
        )
    )

    if !SHOULD_INSTALL_REQUIREMENTS! EQU 1 (
        echo Installing requirements...
        pip install --upgrade -r requirements.txt > "%LOGFILE%" 2>&1
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
        >"%REQ_FINGERPRINT_FILE%" echo %CURRENT_REQUIREMENTS_HASH%
        echo Dependencies installed successfully!
    ) else (
        echo Requirements unchanged, skipping dependency installation
    )
) else (
    echo Virtual environment already exists, skipping installation
    echo To refresh the Torch stack in this venv, run: start_windows.bat --refresh-torch
    echo If CUDA detection is wrong, you can force the wheel channel: start_windows.bat --refresh-torch --cuda=cu128
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
if !ENABLE_CRASH_DIAG! EQU 1 (
    set TAGGUI_ENABLE_FAULTHANDLER=1
    echo Crash diagnostics: ON ^(taggui_fatal.log^)
) else (
    set TAGGUI_ENABLE_FAULTHANDLER=0
    echo Crash diagnostics: OFF
)
python taggui/run_gui.py
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
    echo.
    echo ======================================================
    echo TagGUI exited with error code %EXITCODE%
    echo Check taggui_crash.log and taggui_fatal.log for diagnostics.
    echo ======================================================
    pause
)
exit /b %EXITCODE%
