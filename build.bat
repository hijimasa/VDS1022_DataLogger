@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo === VDS1022I DataLogger Build Script ===
echo.

:: Check/install PyInstaller
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

:: Clean old build
if exist dist\VDS1022_DataLogger rmdir /s /q dist\VDS1022_DataLogger
if exist build\VDS1022_DataLogger rmdir /s /q build\VDS1022_DataLogger

echo Starting build...
python -m PyInstaller vds1022_datalogger.spec

if errorlevel 1 (
    echo.
    echo Build failed.
    pause
    exit /b 1
)

echo.
echo Build complete: dist\VDS1022_DataLogger\VDS1022_DataLogger.exe
echo.

:: Create logs folder
if not exist dist\VDS1022_DataLogger\logs mkdir dist\VDS1022_DataLogger\logs

pause
