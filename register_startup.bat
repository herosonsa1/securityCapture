@echo off
chcp 65001 > NUL
title 개인정보마스킹 - 시작 프로그램 관리 도구

echo ========================================================
echo   개인정보마스킹 자동 실행 관리 도구
echo ========================================================
echo.
echo 1. 윈도우 시작 프로그램 등록 (백그라운드 자동 실행)
echo 2. 윈도우 시작 프로그램 해제
echo 3. 종료
echo.
set /p menu="원하는 작업 번호를 입력하세요 (1-3): "

if "%menu%"=="1" goto REGISTER
if "%menu%"=="2" goto UNREGISTER
if "%menu%"=="3" goto EXIT
goto ERROR

:REGISTER
set "EXE_PATH=%~dp0dist\PrivacyMasker.exe"
if not exist "%EXE_PATH%" (
    set "EXE_PATH=%~dp0PrivacyMasker.exe"
)
if not exist "%EXE_PATH%" (
    echo.
    echo [에러] 실행 파일(PrivacyMasker.exe)을 찾을 수 없습니다.
    echo build_exe.py를 실행하여 먼저 빌드하거나,
    echo 본 배치 파일을 exe 파일과 같은 폴더에 두고 실행해 주세요.
    pause
    exit /b
)

reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PrivacyMasker" /t REG_SZ /d "\"%EXE_PATH%\"" /f
echo.
echo [완료] 성공적으로 시작 프로그램에 등록되었습니다!
echo 이후 윈도우 로그인 시 백그라운드에서 자동으로 구동됩니다.
echo 등록 경로: %EXE_PATH%
pause
exit /b

:UNREGISTER
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "PrivacyMasker" /f
echo.
echo [완료] 성공적으로 시작 프로그램 등록이 해제되었습니다.
pause
exit /b

:ERROR
echo.
echo 잘못된 입력입니다.
pause
exit /b

:EXIT
exit /b
