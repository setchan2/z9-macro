@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM Z9 클라이언트(Z9Star.exe)는 관리자 권한으로 실행된다.
REM 이 매크로가 일반 권한이면 Windows가 게임 창으로 가는 입력을 조용히 버린다.
REM (오류도 안 나고 아무 일도 일어나지 않는다) 그래서 관리자로 올려서 실행한다.

net session > nul 2>&1
if %errorlevel% == 0 goto :elevated

echo 관리자 권한을 요청합니다. UAC 창에서 [예]를 눌러주세요...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:elevated
REM 인터프리터는 '존재하는지'가 아니라 '실제로 실행되는지'로 고른다.
REM py.exe가 Microsoft Store 별칭이면 존재해도 실행에 실패할 수 있다.
REM (괄호 블록이나 && 를 쓰면 cmd 파서가 리다이렉션과 엉키므로 평탄하게 쓴다)
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
echo        python.org 에서 Python 3.11 이상을 설치하고
echo        설치 시 "Add Python to PATH"를 체크하세요.
echo.
pause
exit /b 1

:found
echo 인터프리터: %PY%
echo 매크로를 시작합니다...
%PY% main.py
if errorlevel 1 goto :failed
exit /b

:failed
echo.
echo 실행에 실패했습니다. 위 오류 내용을 확인하세요.
pause
