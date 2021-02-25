set MAX_VERSION=%1
set VRAY_RENDERER=%2
set VRAY_PORT=%3

setx AZ_BATCH_ACCOUNT_URL %AZ_BATCH_ACCOUNT_URL% /M
reg add "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /f /v "AZ_BATCH_SOFTWARE_ENTITLEMENT_TOKEN" /d %AZ_BATCH_SOFTWARE_ENTITLEMENT_TOKEN%

start /wait "vrayspawner2021" "C:\Autodesk\3dsMax2021\vrayspawner2021.exe" "/i" "-port=%VRAY_PORT%" > vrayexe.output.txt

exit /b %errorlevel%
