"""
NetDocker - Точка запуска (без консоли)
Запускается через pythonw.exe — окно консоли не появляется.
При ошибке показывает MessageBox вместо молчаливого падения.
"""
import sys
import os

# Папка с файлами программы
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def show_error(title, msg):
    """Показывает ошибку через tkinter MessageBox (без консоли)"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, msg)
        root.destroy()
    except Exception:
        pass  # если даже tkinter не работает — ничего не сделать


def main():
    # Проверяем зависимости до запуска GUI
    missing = []
    for pkg in ("dnslib", "requests", "psutil", "PIL", "pystray"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        show_error(
            "NetDocker — отсутствуют зависимости",
            f"Не установлены пакеты:\n  {', '.join(missing)}\n\n"
            f"Запустите install.bat или выполните в терминале:\n"
            f"pip install {' '.join(missing)}"
        )
        return

    # Запускаем GUI
    try:
        from gui import main as run_gui
        run_gui()
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        show_error(
            "NetDocker — ошибка запуска",
            f"Произошла ошибка при запуске:\n\n{e}\n\n{err[-800:]}"
        )


if __name__ == "__main__":
    main()
