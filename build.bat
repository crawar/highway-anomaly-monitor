@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if /I "%~1"=="nopause" set "SKIP_PAUSE=1"

set "PY=%~dp0.venv\Scripts\python.exe"
set "OUT=%~dp0dist\CarFind"
set "WEIGHTS=%~dp0Download\yolo26l.pt"

if not exist "%PY%" (
    echo Virtual environment not found: .venv\Scripts\python.exe
    if not defined SKIP_PAUSE pause
    exit /b 1
)

if not exist "%WEIGHTS%" (
    echo Missing weights file: Download\yolo26l.pt
    echo Copy yolo26l.pt into the Download folder, then run this script again.
    if not defined SKIP_PAUSE pause
    exit /b 1
)

if not exist "%~dp0config.json" (
    echo Missing settings file: config.json
    if not defined SKIP_PAUSE pause
    exit /b 1
)

if not exist "%~dp0warning\Pwarning.wav" (
    echo Missing warning\Pwarning.wav
    if not defined SKIP_PAUSE pause
    exit /b 1
)

if not exist "%~dp0warning\Vwarning.wav" (
    echo Missing warning\Vwarning.wav
    if not defined SKIP_PAUSE pause
    exit /b 1
)

echo Installing PyInstaller into the project venv ...
"%PY%" -m pip install "pyinstaller>=6.3" --isolated --cache-dir "%~dp0.pip-cache" -i https://pypi.org/simple --trusted-host pypi.org --trusted-host files.pythonhosted.org
if errorlevel 1 (
    echo Failed to install PyInstaller.
    if not defined SKIP_PAUSE pause
    exit /b 1
)

echo.
echo Discarding previous dist and build folders ...
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist" rmdir /s /q "%~dp0dist"

echo.
echo Building CarFind V1.0.2 onedir package. This can take several minutes ...
"%PY%" -m PyInstaller --noconfirm --clean "%~dp0CarFind.spec"
if errorlevel 1 (
    echo PyInstaller build failed.
    if not defined SKIP_PAUSE pause
    exit /b 1
)

if not exist "%OUT%\CarFind.exe" (
    echo Build finished but CarFind.exe was not found in dist\CarFind
    if not defined SKIP_PAUSE pause
    exit /b 1
)

echo.
echo Copying weights, settings, warning sounds, and Pic folder ...
if not exist "%OUT%\Download" mkdir "%OUT%\Download"
if not exist "%OUT%\warning" mkdir "%OUT%\warning"
if not exist "%OUT%\Pic" mkdir "%OUT%\Pic"
if not exist "%OUT%\Pic\FalsePositive" mkdir "%OUT%\Pic\FalsePositive"

copy /Y "%WEIGHTS%" "%OUT%\Download\yolo26l.pt" >nul
if errorlevel 1 (
    echo Failed to copy yolo26l.pt
    if not defined SKIP_PAUSE pause
    exit /b 1
)

copy /Y "%~dp0config.json" "%OUT%\config.json" >nul
if errorlevel 1 (
    echo Failed to copy config.json
    if not defined SKIP_PAUSE pause
    exit /b 1
)

copy /Y "%~dp0warning\Pwarning.wav" "%OUT%\warning\Pwarning.wav" >nul
copy /Y "%~dp0warning\Vwarning.wav" "%OUT%\warning\Vwarning.wav" >nul
if errorlevel 1 (
    echo Failed to copy warning wav files
    if not defined SKIP_PAUSE pause
    exit /b 1
)

echo.
echo Package ready: CarFind V1.0.2
echo   %OUT%\CarFind.exe
echo Folder contents include:
echo   CarFind.exe
echo   _internal\
echo   config.json
echo   Download\yolo26l.pt
echo   warning\
echo   Pic\
echo.
echo Copy the whole dist\CarFind folder to another PC. Do not copy only the exe.
if not defined SKIP_PAUSE pause
exit /b 0
