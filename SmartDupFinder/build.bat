@echo off
title Smart Photo Comparator - Portable EXE Builder
echo ====================================================
echo  Smart Photo Comparator - Portable EXE Builder
echo ====================================================
echo.
echo Check virtual environment and build requirements...
if not exist "..\.venv\Scripts\pyinstaller.exe" (
    echo [INFO] Installing PyInstaller in the virtual environment...
    ..\.venv\Scripts\python.exe -m pip install pyinstaller
)
echo.
echo Building portable single-file executable (-F / --onefile)...
..\.venv\Scripts\pyinstaller --noconsole --onefile --name "SmartPhotoComparator" smart_dup_finder.py
echo.
echo ====================================================
echo  Build Complete!
echo  Portable EXE is located in: SmartDupFinder\dist\
echo ====================================================
pause
