@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "APP_DIR=%SCRIPT_DIR%medfollow"
set "PYTHON_EXE=C:\Users\abdel\AppData\Local\Programs\Python\Python313\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Python introuvable: "%PYTHON_EXE%"
    exit /b 1
)

pushd "%APP_DIR%"
"%PYTHON_EXE%" -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
set "EXIT_CODE=%ERRORLEVEL%"

popd

exit /b %EXIT_CODE%
