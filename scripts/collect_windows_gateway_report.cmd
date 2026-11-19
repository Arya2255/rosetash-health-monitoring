@echo off
setlocal EnableExtensions
if "%~1"=="" goto usage
set "REPORT=%USERPROFILE%\Desktop\roztash-gateway-report-%~1.json"
if not "%~3"=="" goto with_mac
if not "%~2"=="" goto with_ip
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect_windows_gateway_report.ps1" -GatewayId "%~1" > "%REPORT%"
goto check_result
:with_mac
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect_windows_gateway_report.ps1" -GatewayId "%~1" -GatewayIp "%~2" -BandMac "%~3" > "%REPORT%"
goto check_result
:with_ip
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0collect_windows_gateway_report.ps1" -GatewayId "%~1" -GatewayIp "%~2" > "%REPORT%"
:check_result
if errorlevel 1 goto failed
echo Report saved to:
echo %REPORT%
exit /b 0
:usage
echo Usage:
echo %~nx0 GATEWAY_ID [GATEWAY_IP] [BAND_MAC]
echo Example:
echo %~nx0 gw-example 192.168.1.51 aa:bb:cc:dd:ee:01
echo Leave the app running while collecting the report.
exit /b 2
:failed
echo Report collection failed. Review the PowerShell error above.
if exist "%REPORT%" del "%REPORT%"
exit /b 1
