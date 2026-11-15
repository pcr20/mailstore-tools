@echo off
setlocal enabledelayedexpansion
set STAGE=C:\Users\pcr20\OneDrive\Apps\_fbwork
set FB=C:\Users\pcr20\OneDrive\Apps\MailstoreLup\Application\Firebird4_x86
set DATA=C:\Users\pcr20\OneDrive\Apps\MailstoreLup\Data
set WORK=%TEMP%\msfb
set OUT=%STAGE%\out.txt

echo [run.bat] starting > "%OUT%"
echo [run.bat] staging folder %STAGE% >> "%OUT%"

rem --- unpack bundled python libs ---
if not exist "%STAGE%\pylib\firebird" (
  echo [run.bat] extracting pylib.zip >> "%OUT%"
  powershell -NoProfile -Command "Expand-Archive -Force -Path '%STAGE%\pylib.zip' -DestinationPath '%STAGE%'" >> "%OUT%" 2>&1
)

rem --- fresh copy of the db + its key side by side ---
if exist "%WORK%" rmdir /s /q "%WORK%"
mkdir "%WORK%"
copy /y "%DATA%\MailStoreMaster.fdb" "%WORK%\" >> "%OUT%" 2>&1
copy /y "%DATA%\MailStoreMaster.key" "%WORK%\" >> "%OUT%" 2>&1

rem --- locate python ---
set PY=
py -3 --version >nul 2>&1 && set PY=py -3
if "!PY!"=="" ( python --version >nul 2>&1 && set PY=python )
if "!PY!"=="" (
  echo [run.bat] ERROR: no python on PATH ^(tried 'py -3' and 'python'^) >> "%OUT%"
  goto :end
)
echo [run.bat] using python: !PY! >> "%OUT%"

rem --- run from the firebird root so fbclient.dll + its dependent dlls resolve ---
cd /d "%FB%"
!PY! "%STAGE%\dump_schema.py" "%WORK%\MailStoreMaster.fdb" "%FB%\fbclient.dll" >> "%OUT%" 2>&1

:end
echo [run.bat] finished exit=%errorlevel% >> "%OUT%"
echo DONE
type "%OUT%"
