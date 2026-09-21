@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if /I "%~1"=="nopause" set "SKIP_PAUSE=1"

set "PY=%~dp0.venv\Scripts\python.exe"
set "WEIGHTS=%~dp0Download\yolo26l.pt"

:: Version comes from app\__init__.py (VERSION = "V1.1.2"); the package folder
:: is dist\CarFind-<version> so several versions can sit side by side.
set "VER="
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"VERSION" "%~dp0app\__init__.py"') do set "VER=%%v"
set "VER=%VER: =%"
set "VER=%VER:"=%"
if not defined VER (
    echo Could not read VERSION from app\__init__.py
    if not defined SKIP_PAUSE pause
    exit /b 1
)
set "NAME=CarFind-%VER%"
set "OUT=%~dp0dist\%NAME%"

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

if not exist "%~dp0warning\Rwarning.wav" (
    echo Missing warning\Rwarning.wav
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
echo Discarding previous build folder and dist\%NAME% (other versions are kept) ...
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%OUT%" rmdir /s /q "%OUT%"

echo.
echo Building %NAME% onedir package. This can take several minutes ...
"%PY%" -m PyInstaller --noconfirm --clean "%~dp0CarFind.spec"
if errorlevel 1 (
    echo PyInstaller build failed.
    if not defined SKIP_PAUSE pause
    exit /b 1
)

if not exist "%OUT%\CarFind.exe" (
    echo Build finished but CarFind.exe was not found in dist\%NAME%
    if not defined SKIP_PAUSE pause
    exit /b 1
)

echo.
echo Copying weights, settings, warning sounds, and Pic folder ...
if not exist "%OUT%\Download" mkdir "%OUT%\Download"
if not exist "%OUT%\warning" mkdir "%OUT%\warning"
if not exist "%OUT%\Pic" mkdir "%OUT%\Pic"
if not exist "%OUT%\Pic\FalsePositive" mkdir "%OUT%\Pic\FalsePositive"
if not exist "%OUT%\logs" mkdir "%OUT%\logs"

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
copy /Y "%~dp0warning\Rwarning.wav" "%OUT%\warning\Rwarning.wav" >nul
if errorlevel 1 (
    echo Failed to copy warning wav files
    if not defined SKIP_PAUSE pause
    exit /b 1
)

echo.
echo Package ready: %NAME%
echo   %OUT%\CarFind.exe
echo Folder contents include:
echo   CarFind.exe
echo   _internal\
echo   config.json
echo   Download\yolo26l.pt
echo   warning\
echo   Pic\
echo   logs\   (diagnostic logs are written here at runtime)
echo.
echo Copy the whole dist\%NAME% folder to another PC. Do not copy only the exe.
if not defined SKIP_PAUSE pause
exit /b 0
