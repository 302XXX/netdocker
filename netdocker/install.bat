@echo off
echo ==========================================
echo    NetDocker - Установка зависимостей
echo ==========================================
echo.

where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ОШИБКА] Python не найден! Установите Python 3.8+ с python.org
    pause
    exit /b 1
)

echo Установка Python-пакетов...
python -m pip install --upgrade pip
python -m pip install dnslib requests psutil pillow pystray

echo.
echo ==========================================
echo    Установка завершена!
echo.
echo    Для запуска используйте:
echo    start.bat (или python main.py)
echo ==========================================
pause
