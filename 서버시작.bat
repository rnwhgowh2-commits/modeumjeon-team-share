@echo off
chcp 65001 >nul
title 르무통 재고 서버
cd /d "%~dp0_시스템"

echo ==========================================
echo  르무통 재고 업데이트 서버 시작
echo  http://127.0.0.1:5052
echo ==========================================
echo.

REM 5초 후 브라우저 자동 오픈 (서버 부팅 대기)
start "" /B cmd /C "timeout /t 5 /nobreak >nul && start http://127.0.0.1:5052"

python app.py

echo.
echo 서버가 종료되었습니다. 아무 키나 누르면 창이 닫힙니다.
pause >nul
