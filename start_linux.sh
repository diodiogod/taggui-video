#!/bin/bash

LOGFILE="taggui_setup.log"
SKIP_GIT=0
CLEAR_CACHE=0
CLEAN_OLD=0

echo "Logging to $LOGFILE"
echo ""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-git) SKIP_GIT=1 ;;
        --clear-cache) CLEAR_CACHE=1 ;;
        --clean-old) CLEAN_OLD=1 ;;
    esac
    shift
done

# Check if git repo exists
if [ ! -d .git ]; then
    echo "Note: Not a git repository. Skipping git pull."
    echo "$(date) - No .git directory found" >> "$LOGFILE"
else
    # Optional: git pull (can be skipped with flag)
    if [ $SKIP_GIT -eq 0 ]; then
        echo "Pulling latest changes..."
        if ! git pull >> "$LOGFILE" 2>&1; then
            echo ""
            echo "======================================================"
            echo "WARNING: Could not download latest updates"
            echo "======================================================"
            echo "This usually means:"
            echo " - Your internet connection is offline"
            echo " - GitHub is temporarily unavailable"
            echo " - You have a network/firewall issue"
            echo ""
            echo "You can still run TagGUI with your current version."
            echo "$(date) - Git pull failed" >> "$LOGFILE"
            echo ""
            read -p "Continue with setup? (Y/N): " CONTINUE
            if [[ ! $CONTINUE =~ ^[Yy]$ ]]; then
                exit 1
            fi
            echo "OK, skipping update and continuing..."
            echo ""
        fi
    else
        echo "Skipping git pull (--skip-git flag)"
    fi
fi

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python3 not installed. Please install Python 3.10+"
    exit 1
fi

PYVER=$(python3 --version 2>&1 | awk '{print $2}')
echo "Found Python $PYVER"

# Check if requirements.txt exists
if [ ! -f requirements.txt ]; then
    echo "ERROR: requirements.txt not found in current directory"
    echo "Make sure you are running this script from the TagGUI folder"
    exit 1
fi

# Check for venv in current directory, then parent directory
VENV_PATH="venv"
VENV_EXISTS=0

if [ ! -f "$VENV_PATH/bin/activate" ]; then
    if [ -f "../venv/bin/activate" ]; then
        VENV_PATH="../venv"
        VENV_EXISTS=1
        echo "Found virtual environment in parent directory"
    else
        echo "Creating virtual environment..."
        python3 -m venv "$VENV_PATH" >> "$LOGFILE" 2>&1 || {
            echo "ERROR: Failed to create venv"
            exit 1
        }
    fi
else
    VENV_EXISTS=1
fi

# Activate venv
echo "Activating virtual environment..."
source "$VENV_PATH/bin/activate" || {
    echo "ERROR: Failed to activate virtual environment"
    exit 1
}

# Only install if venv was just created
if [ $VENV_EXISTS -eq 0 ]; then
    echo "Upgrading pip..."
    python -m pip install --upgrade pip >> "$LOGFILE" 2>&1

    echo "Installing requirements..."
    pip install -r requirements.txt >> "$LOGFILE" 2>&1 || {
        echo ""
        echo "======================================================"
        echo "ERROR: Failed to install dependencies"
        echo "======================================================"
        echo "This usually means:"
        echo " - Your internet connection is offline"
        echo " - A Python package is not compatible with your system"
        echo " - A package server is temporarily unavailable"
        echo ""
        echo "Check the log file for details: $LOGFILE"
        echo ""
        exit 1
    }

    echo "Dependencies installed successfully!"
else
    echo "Virtual environment already exists, skipping installation"
fi

# Optional: Clear pip cache
if [ $CLEAR_CACHE -eq 1 ]; then
    echo "Clearing pip cache..."
    pip cache purge >> "$LOGFILE" 2>&1
    echo "Cache cleared."
fi

# Optional: Clean old packages not in requirements.txt
if [ $CLEAN_OLD -eq 1 ]; then
    echo "Cleaning old packages not in requirements.txt..."
    pip list --format=freeze > /tmp/current_packages.txt
    grep -v -f requirements.txt /tmp/current_packages.txt > /tmp/old_packages.txt 2>/dev/null || true
    if [ -s /tmp/old_packages.txt ]; then
        while IFS= read -r package; do
            pip uninstall -y "${package%=*}" >> "$LOGFILE" 2>&1
        done < /tmp/old_packages.txt
        rm /tmp/old_packages.txt /tmp/current_packages.txt
        echo "Old packages removed."
    fi
fi

# Run TagGUI
echo ""
echo "======================================================"
echo "Starting TagGUI..."
echo "======================================================"
echo ""
python taggui/run_gui.py
