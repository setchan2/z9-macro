@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================
echo  Z9 매크로 - exe 만들기 (파일 하나로 실행)
echo ============================================
echo.

rem 파이썬 실행기를 실제로 돌려 보고 되는 것을 고른다.
rem (py 는 Microsoft Store 별칭인 경우가 있어 존재 여부만으로는 알 수 없다)
set PYEXE=
for %%P in ("py -3" "py" "python") do (
    if not defined PYEXE (
        %%~P -c "import sys" >nul 2>&1 && set "PYEXE=%%~P"
    )
)
if not defined PYEXE (
    echo [실패] 파이썬을 찾지 못했습니다.
    pause
    exit /b 1
)
echo 파이썬: %PYEXE%

%PYEXE% -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo PyInstaller 를 설치합니다...
    %PYEXE% -m pip install pyinstaller
    if errorlevel 1 (
        echo [실패] PyInstaller 설치에 실패했습니다.
        pause
        exit /b 1
    )
)

rem exe 안에 담을 처음 설정(설정 파일 · 라이브러리 · 꾸미기 이미지)을 build\seed 에 모은다.
echo.
echo exe 에 담을 처음 설정을 모읍니다...
%PYEXE% build_seed.py
if errorlevel 1 (
    echo [실패] 처음 설정을 모으지 못했습니다.
    pause
    exit /b 1
)

echo.
echo 빌드 중입니다. 2~3분 걸립니다...
echo.

rem 파일 하나(--onefile)에 글꼴과 처음 설정을 함께 담는다.
rem 경로는 %~dp0 로 절대 경로를 준다 — --specpath 를 쓰면 상대 경로가 build 폴더 기준이 된다.
%PYEXE% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name "Z9매크로" ^
    --version-file "%~dp0build\version.txt" ^
    --uac-admin ^
    --add-data "%~dp0fonts;fonts" ^
    --add-data "%~dp0build\seed;seed" ^
    --distpath "%~dp0release" ^
    --workpath "%~dp0build\work" ^
    --specpath "%~dp0build" ^
    main.py

if errorlevel 1 (
    echo.
    echo [실패] 빌드 중 오류가 발생했습니다. 위 메시지를 확인하세요.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  완료:  release\Z9매크로.exe
echo ============================================
echo.
echo  - 이 exe 파일 하나만 있으면 됩니다. 원하는 폴더에 옮겨 두고 실행하세요.
echo  - 처음 켜면 exe 옆에 data\ 와 library\ 폴더를 만들고, 빌드할 때의
echo    매크로 · 조건 · 낚시 설정을 풀어 놓습니다. 이미 있으면 건드리지 않습니다.
echo  - 그 뒤로 exe 에서 고친 설정은 exe 옆 data\ 에 저장됩니다.
echo  - 실행하면 관리자 권한을 묻습니다. 허용해야 입력이 게임에 들어갑니다.
echo.
pause
