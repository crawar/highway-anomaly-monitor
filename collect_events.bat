@echo off
setlocal
:: Collect Windows event-log evidence about crashes / reboots / display-driver
:: resets on THIS machine and write it to event-report.txt next to this file.
:: Read-only: nothing on the system is changed. Copy the txt file back for analysis.
set "OUT=%~dp0event-report.txt"
set "HOURS=48"
set /a MS=%HOURS%*3600000

echo CarFind event report > "%OUT%"
echo generated: %date% %time%  window: last %HOURS% hours >> "%OUT%"
net session >nul 2>&1
if errorlevel 1 (
    echo NOTE: not running as administrator - dump and WER listings may be incomplete >> "%OUT%"
) else (
    echo running as administrator >> "%OUT%"
)
echo. >> "%OUT%"

echo [1/13] system info
echo ===== SYSTEM INFO ===== >> "%OUT%"
powershell -NoProfile -Command "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,LastBootUpTime,TotalVisibleMemorySize,FreePhysicalMemory | Format-List" >> "%OUT%" 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model | Format-List" >> "%OUT%" 2>&1

echo [2/13] gpu info
echo ===== GPU / DISPLAY DRIVER ===== >> "%OUT%"
powershell -NoProfile -Command "Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion,DriverDate,VideoProcessor,Status,CurrentHorizontalResolution,CurrentVerticalResolution | Format-List" >> "%OUT%" 2>&1

echo [3/13] application crashes and hangs
echo ===== APPLICATION LOG: crashes (1000), WER (1001), hangs (1002), .NET (1026) ===== >> "%OUT%"
wevtutil qe Application /q:"*[System[(EventID=1000 or EventID=1001 or EventID=1002 or EventID=1026) and TimeCreated[timediff(@SystemTime) <= %MS%]]]" /f:text /rd:true /c:100 >> "%OUT%" 2>&1

echo [4/13] reboots, bugchecks, display driver resets
echo ===== SYSTEM LOG: power loss (41), bugcheck (1001), dirty shutdown (6008), display TDR (4101), boot/shutdown (12/13/6005/6006) ===== >> "%OUT%"
wevtutil qe System /q:"*[System[(EventID=41 or EventID=1001 or EventID=6008 or EventID=4101 or EventID=6005 or EventID=6006 or EventID=12 or EventID=13 or EventID=14 or EventID=1074 or EventID=4109) and TimeCreated[timediff(@SystemTime) <= %MS%]]]" /f:text /rd:true /c:200 >> "%OUT%" 2>&1

echo [5/13] display / hardware / power providers
echo ===== SYSTEM LOG: Display, GPU vendors, WHEA hardware errors, Kernel-Power ===== >> "%OUT%"
wevtutil qe System /q:"*[System[Provider[@Name='Display' or @Name='nvlddmkm' or @Name='amdkmdag' or @Name='amdwddmg' or @Name='igfx' or @Name='igfxn' or @Name='Microsoft-Windows-WHEA-Logger' or @Name='Microsoft-Windows-Kernel-Power' or @Name='Microsoft-Windows-Kernel-Processor-Power' or @Name='Microsoft-Windows-DxgKrnl'] and TimeCreated[timediff(@SystemTime) <= %MS%]]]" /f:text /rd:true /c:200 >> "%OUT%" 2>&1

echo [6/13] all critical / error events in System
echo ===== SYSTEM LOG: all Critical/Error (max 150) ===== >> "%OUT%"
wevtutil qe System /q:"*[System[(Level=1 or Level=2) and TimeCreated[timediff(@SystemTime) <= %MS%]]]" /f:text /rd:true /c:150 >> "%OUT%" 2>&1

echo [7/13] all critical / error events in Application
echo ===== APPLICATION LOG: all Critical/Error (max 150) ===== >> "%OUT%"
wevtutil qe Application /q:"*[System[(Level=1 or Level=2) and TimeCreated[timediff(@SystemTime) <= %MS%]]]" /f:text /rd:true /c:150 >> "%OUT%" 2>&1

echo [8/13] windows error reporting archive
echo ===== WER REPORTS (Report.wer key fields, last %HOURS% hours) ===== >> "%OUT%"
powershell -NoProfile -Command "$since=(Get-Date).AddHours(-%HOURS%); $roots=@(\"$env:ProgramData\Microsoft\Windows\WER\ReportArchive\",\"$env:ProgramData\Microsoft\Windows\WER\ReportQueue\",\"$env:LOCALAPPDATA\Microsoft\Windows\WER\ReportArchive\",\"$env:LOCALAPPDATA\Microsoft\Windows\WER\ReportQueue\"); foreach($r in $roots){ if(Test-Path $r){ Get-ChildItem $r -Directory | Where-Object { $_.LastWriteTime -gt $since } | Sort-Object LastWriteTime -Descending | ForEach-Object { Write-Output ('--- ' + $_.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') + '  ' + $_.FullName); $wer=Join-Path $_.FullName 'Report.wer'; if(Test-Path $wer){ Select-String -Path $wer -Pattern '^(EventType|AppName|AppPath|AppVersion|FriendlyEventName|ReportDescription|Sig\[[0-9]\]\.(Name|Value)|DynamicSig\[[0-9]+\]\.Value)=' | ForEach-Object { $_.Line } } } } }" >> "%OUT%" 2>&1

echo [9/13] kernel dumps
echo ===== KERNEL / MINI DUMPS ===== >> "%OUT%"
if exist "%SystemRoot%\Minidump" dir "%SystemRoot%\Minidump" >> "%OUT%" 2>&1
if exist "%SystemRoot%\MEMORY.DMP" dir "%SystemRoot%\MEMORY.DMP" >> "%OUT%" 2>&1
if exist "%SystemRoot%\LiveKernelReports" dir /s "%SystemRoot%\LiveKernelReports" >> "%OUT%" 2>&1

echo [10/13] bios and cpu microcode
echo ===== BIOS / CPU MICROCODE (Raptor Lake needs 0x12F or newer) ===== >> "%OUT%"
powershell -NoProfile -Command "Get-CimInstance Win32_BIOS | Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate | Format-List" >> "%OUT%" 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Processor | Select-Object Name,Description,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed | Format-List" >> "%OUT%" 2>&1
echo Microcode revision (REG_BINARY, little endian: 2F 01 00 00 = 0x12F): >> "%OUT%"
reg query "HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0" /v "Update Revision" >> "%OUT%" 2>&1
reg query "HKLM\HARDWARE\DESCRIPTION\System\CentralProcessor\0" /v "Previous Update Revision" >> "%OUT%" 2>&1

echo [11/13] whea hardware errors and all app crashes, last 90 days
echo ===== SYSTEM LOG: WHEA hardware errors, last 90 days ===== >> "%OUT%"
wevtutil qe System /q:"*[System[Provider[@Name='Microsoft-Windows-WHEA-Logger'] and TimeCreated[timediff(@SystemTime) <= 7776000000]]]" /f:text /rd:true /c:100 >> "%OUT%" 2>&1
echo ===== SYSTEM LOG: bugchecks (1001) and unexpected reboots (41), last 90 days ===== >> "%OUT%"
wevtutil qe System /q:"*[System[(EventID=41 or EventID=1001) and TimeCreated[timediff(@SystemTime) <= 7776000000]]]" /f:text /rd:true /c:100 >> "%OUT%" 2>&1
echo ===== APPLICATION LOG: every app crash (1000), last 90 days - which exe, which module, which code ===== >> "%OUT%"
powershell -NoProfile -Command "Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000; StartTime=(Get-Date).AddDays(-90)} -ErrorAction SilentlyContinue | ForEach-Object { $m=$_.Message -split \"`n\"; ($_.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss') + '  ' + ($m[0] -replace '^[^:]*:\s*','') + '  |  ' + ($m[1] -replace '^[^:]*:\s*','') + '  |  ' + ($m[2] -replace '^[^:]*:\s*','')) }" >> "%OUT%" 2>&1

echo [12/13] copy minidumps next to this file (needs administrator)
echo ===== MINIDUMP COPY ===== >> "%OUT%"
if exist "%SystemRoot%\Minidump\*.dmp" (
    if not exist "%~dp0minidump" mkdir "%~dp0minidump"
    copy /Y "%SystemRoot%\Minidump\*.dmp" "%~dp0minidump\" >> "%OUT%" 2>&1
) else (
    echo no minidump files found or no permission >> "%OUT%"
)

echo [13/13] dxdiag (which monitor is on which GPU, driver details) - takes about 30 seconds
dxdiag /whql:off /t "%~dp0dxdiag.txt"
if exist "%~dp0dxdiag.txt" (echo dxdiag written to dxdiag.txt >> "%OUT%") else (echo dxdiag failed >> "%OUT%")

echo.
echo Done. Report written to:
echo   %OUT%
echo Copy this file back together with the logs folder.
pause
