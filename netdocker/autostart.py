"""
NetDocker — Автозапуск с Windows
================================

Управляет автозапуском программы при входе в Windows через ключ реестра
HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run.

Почему именно так:
  • HKCU\\...\\Run НЕ требует прав администратора для записи;
  • запускаем start.bat, который сам поднимает права (UAC) и стартует GUI;
  • на не-Windows функции тихо возвращают False/безопасные значения.

API:
  is_supported()      -> bool   — поддерживается ли автозапуск на этой ОС
  is_enabled()        -> bool   — включён ли сейчас
  enable()            -> (ok, msg)
  disable()           -> (ok, msg)
  set_enabled(flag)   -> (ok, msg)
"""

import logging
import os
import sys

log = logging.getLogger("NetDocker.Autostart")

IS_WINDOWS = sys.platform == "win32"

APP_NAME = "NetDocker"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_supported() -> bool:
    return IS_WINDOWS


def _start_command() -> str:
    """Команда, которая будет прописана в автозапуск.

    Запускаем start.bat (он сам поднимет права и GUI без консоли).
    Путь оборачиваем в кавычки на случай пробелов.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    bat = os.path.join(base_dir, "start.bat")
    return f'"{bat}"'


def _open_run_key(write=False):
    import winreg
    access = winreg.KEY_WRITE if write else winreg.KEY_READ
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, access)


def is_enabled() -> bool:
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with _open_run_key(write=False) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except OSError:
        return False


def enable() -> tuple:
    if not IS_WINDOWS:
        return False, "Автозапуск доступен только в Windows"
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _start_command())
        log.info("Автозапуск включён")
        return True, "Автозапуск с Windows включён"
    except Exception as exc:
        log.warning("Не удалось включить автозапуск: %s", exc)
        return False, f"Не удалось включить автозапуск: {exc}"


def disable() -> tuple:
    if not IS_WINDOWS:
        return False, "Автозапуск доступен только в Windows"
    import winreg
    try:
        with _open_run_key(write=True) as key:
            winreg.DeleteValue(key, APP_NAME)
        log.info("Автозапуск выключен")
        return True, "Автозапуск с Windows выключен"
    except FileNotFoundError:
        return True, "Автозапуск и так был выключен"
    except OSError as exc:
        # Значения нет — считаем, что уже выключено
        if getattr(exc, "winerror", None) == 2:
            return True, "Автозапуск и так был выключен"
        log.warning("Не удалось выключить автозапуск: %s", exc)
        return False, f"Не удалось выключить автозапуск: {exc}"


def set_enabled(flag: bool) -> tuple:
    return enable() if flag else disable()
