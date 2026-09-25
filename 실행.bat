@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM 일반 권한 실행. 게임이 관리자 권한으로 돌고 있으면 입력이 차단되므로
REM 보통은 [관리자로 실행.bat]을 쓰는 게 맞다.

set "PY="

py -3 -c "pass" > nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto :found

py -c "pass" > nul 2>&1
if not errorlevel 1 set "PY=py"
if defined PY goto :found

python -c "pass" > nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto :found

echo.
echo [오류] 실행 가능한 Python을 찾지 못했습니다.
echo        python.org 에서 Python 3.11 이상을 설치하세요.
echo.
pause
exit /b 1

:found
%PY% main.py
if errorlevel 1 goto :failed
exit /b

:failed
echo.
echo 실행에 실패했습니다. 위 오류 내용을 확인하세요.
pause
