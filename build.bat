@echo off
chcp 65001 > nul
echo === VDS1022I DataLogger ビルドスクリプト ===
echo.

:: PyInstallerの確認・インストール
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstallerをインストールしています...
    pip install pyinstaller
)

:: 古いビルドを削除
if exist dist\VDS1022_DataLogger rmdir /s /q dist\VDS1022_DataLogger
if exist build\VDS1022_DataLogger rmdir /s /q build\VDS1022_DataLogger

echo ビルドを開始します...
pyinstaller vds1022_datalogger.spec

if errorlevel 1 (
    echo.
    echo ビルドに失敗しました。
    pause
    exit /b 1
)

echo.
echo ビルド完了: dist\VDS1022_DataLogger\VDS1022_DataLogger.exe
echo.

:: 動作確認用: logsフォルダを作成
if not exist dist\VDS1022_DataLogger\logs mkdir dist\VDS1022_DataLogger\logs

pause
