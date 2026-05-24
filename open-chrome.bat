@echo off
REM Open Modeumjeon (Fly.io) in Chrome
REM English filename - avoids Korean encoding display issues

set "URL=https://modeumjeon-team-share.fly.dev"

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

start "" "%URL%"
