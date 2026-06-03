@echo off
REM Open Modeumjeon (AWS Lightsail) in Chrome - English only to avoid CP949 issues

set "URL=http://54.116.196.90"

set "CHROME1=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "CHROME2=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
set "CHROME3=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if exist "%CHROME1%" (
    start "" "%CHROME1%" "%URL%"
    exit /b
)
if exist "%CHROME2%" (
    start "" "%CHROME2%" "%URL%"
    exit /b
)
if exist "%CHROME3%" (
    start "" "%CHROME3%" "%URL%"
    exit /b
)

REM Fallback - default browser
start "" "%URL%"
