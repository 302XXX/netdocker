@echo off
setlocal EnableExtensions

:: ============================================================================
:: NetDocker — запуск СРАЗУ от имени администратора
:: ----------------------------------------------------------------------------
:: Логика:
::   1) Проверяем, есть ли права администратора.
::   2) Если НЕТ — перезапускаем этот же .bat через UAC (Verb RunAs) и выходим.
::   3) Если ДА — находим pythonw.exe и запускаем GUI без окна консоли.
:: ============================================================================

:: ── Шаг 1: проверка прав администратора ─────────────────────────────────────
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Requesting administrator rights...
    :: Перезапускаем сам себя с повышением прав. -Verb RunAs вызывает UAC.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

:: ── Сюда попадаем только уже с правами администратора ────────────────────────
:: Рабочая папка = папка этого .bat (важно при запуске через UAC).
cd /d "%~dp0"
set "SCRIPT=%~dp0start.pyw"

:: ── Шаг 2: ищем python.exe ──────────────────────────────────────────────────
set "PYTHON_EXE="
for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined PYTHON_EXE set "PYTHON_EXE=%%i"
)

if not defined PYTHON_EXE (
    echo ERROR: Python not found. Install Python from python.org
    pause
    exit /b 1
)

:: ── Шаг 3: предпочитаем pythonw.exe (запуск без окна консоли) ────────────────
set "PYTHONW_EXE=%PYTHON_EXE:python.exe=pythonw.exe%"
if not exist "%PYTHONW_EXE%" set "PYTHONW_EXE=%PYTHON_EXE%"

:: ── Шаг 4: запускаем NetDocker ──────────────────────────────────────────────
start "" "%PYTHONW_EXE%" "%SCRIPT%"

endlocal
