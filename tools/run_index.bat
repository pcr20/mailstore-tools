@echo off
setlocal enabledelayedexpansion
set STAGE=C:\Users\pcr20\OneDrive\Apps\_msidx
set FB=C:\Users\pcr20\OneDrive\Apps\Mailstore\Application\Firebird4_x86
set DATA=C:\Users\pcr20\OneDrive\Apps\Mailstore\Data
set WORK=%TEMP%\msidx
set OUT=%STAGE%\index_log.txt
set DB=%STAGE%\mailstore_index.db

echo [idx] starting > "%OUT%"

if not exist "%STAGE%\pylib\firebird" (
  powershell -NoProfile -Command "Expand-Archive -Force -Path '%STAGE%\pylib.zip' -DestinationPath '%STAGE%'" >> "%OUT%" 2>&1
)

if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
copy /y "%DATA%\MailStoreFileGroup.fdb" "%WORK%\" >> "%OUT%" 2>&1
copy /y "%DATA%\MailStoreFileGroup.key" "%WORK%\" >> "%OUT%" 2>&1

set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if "!PY!"=="" ( python --version >nul 2>&1 && set PY=python )
if "!PY!"=="" ( echo [idx] ERROR: no python >> "%OUT%" & goto :end )
echo [idx] python: !PY! >> "%OUT%"

if exist "%DB%" del /q "%DB%"
cd /d "%FB%"
!PY! "%STAGE%\build_index.py" "%FB%\fbclient.dll" "%WORK%\MailStoreFileGroup.fdb" "%DB%" >> "%OUT%" 2>&1

:end
echo [idx] finished exit=%errorlevel% >> "%OUT%"
echo DONE
