@echo off
setlocal
set "BOT_SCRIPT=%~dp0bot_giam_sat.py"

echo ==============================================
echo   BO PHAN DIEU KHIEN: DONG BOT GIAM SAT NGAM
echo ==============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$target = [System.IO.Path]::GetFullPath($env:BOT_SCRIPT); " ^
  "$processes = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -and $_.CommandLine.IndexOf($target, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 }; " ^
  "if (-not $processes) { Write-Host 'Khong tim thay bot vision_bot dang chay.'; exit 0 }; " ^
  "foreach ($process in $processes) { Stop-Process -Id $process.ProcessId -Force; Write-Host ('Da tat bot PID {0} ({1})' -f $process.ProcessId, $process.Name) }"

echo.
echo Da xu ly lenh tat bot. Script nay chi tat process dang chay bot_giam_sat.py.
pause
