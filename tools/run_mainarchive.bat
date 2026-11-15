@echo off
setlocal enabledelayedexpansion
set STAGE=C:\Users\pcr20\OneDrive\Apps\_fbwork
set FB=C:\Users\pcr20\OneDrive\Apps\Mailstore\Application\Firebird4_x86
set DATA=C:\Users\pcr20\OneDrive\Apps\Mailstore\Data
set WORK=%TEMP%\msfb2
set OUT=%STAGE%\out2.txt

echo [run2] starting > "%OUT%"

if not exist "%STAGE%\pylib\firebird" (
  powershell -NoProfile -Command "Expand-Archive -Force -Path '%STAGE%\pylib.zip' -DestinationPath '%STAGE%'" >> "%OUT%" 2>&1
)

if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
copy /y "%DATA%\MailStoreMaster.fdb"    "%WORK%\" >> "%OUT%" 2>&1
copy /y "%DATA%\MailStoreMaster.key"    "%WORK%\" >> "%OUT%" 2>&1
copy /y "%DATA%\MailStoreFileGroup.fdb" "%WORK%\" >> "%OUT%" 2>&1
copy /y "%DATA%\MailStoreFileGroup.key" "%WORK%\" >> "%OUT%" 2>&1

set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if "!PY!"=="" ( python --version >nul 2>&1 && set PY=python )
if "!PY!"=="" ( echo [run2] ERROR: no python >> "%OUT%" & goto :end )
echo [run2] python: !PY! >> "%OUT%"

cd /d "%FB%"
!PY! "%STAGE%\dump_schema.py" "%FB%\fbclient.dll" "%WORK%\MailStoreMaster.fdb" "%WORK%\MailStoreFileGroup.fdb" >> "%OUT%" 2>&1

:end
echo [run2] finished exit=%errorlevel% >> "%OUT%"
echo DONE
