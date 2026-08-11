@echo off
setlocal
pushd "%~dp0"

if /I "%~1"=="clean" (
    latexmk -C main.tex
) else (
    latexmk -pdf main.tex
)

set "BUILD_EXIT=%ERRORLEVEL%"
popd
exit /b %BUILD_EXIT%
