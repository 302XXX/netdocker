"""
NetDocker - Системный трей (system tray)
Иконка в трее: зелёная (работает) / красная (остановлен) / жёлтая (перезапуск)
Контекстное меню: Старт / Стоп / Перезапуск / Показать окно / Выход

Интеграция с gui.py:
    TrayIcon(app)          - создаёт иконку (app - экземпляр NetDockerApp)
    .start()               - запускает трей в фоновом потоке
    .set_running()         - зелёная иконка
    .set_stopped()         - красная иконка
    .set_waiting(msg)      - жёлтая иконка + сообщение
    .stop()                - останавливает трей
"""
import threading
import logging
from PIL import Image, ImageDraw

log = logging.getLogger("NetDocker.Tray")

# Цвета (такие же как в gui.py)
GREEN = (59, 165, 93)       # #3ba55d
RED = (237, 66, 69)         # #ed4245
YELLOW = (250, 166, 26)     # #faa61a


def _make_icon(color, size=64):
    """Создаёт PNG-иконку - цветной круг на прозрачном фоне"""
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = size // 8
    draw.ellipse([margin, margin, size - margin, size - margin], fill=color)
    # Белая обводка для контраста
    draw.ellipse([margin + 1, margin + 1, size - margin - 1, size - margin - 1],
                 outline=(255, 255, 255, 30), width=1)
    return img


class TrayIcon:
    """Иконка в системном трее с управлением по состоянию DNS-сервера"""

    def __init__(self, app):
        """
        app - экземпляр NetDockerApp (tkinter Tk).
        Нужен для app.ctrl._start/_stop/_restart и app.after()
        """
        self._app = app
        self._icon = None
        self._thread = None

        # Заранее готовим иконки для трёх состояний
        self._img_running = _make_icon(GREEN)
        self._img_stopped = _make_icon(RED)
        self._img_waiting = _make_icon(YELLOW)

    # --- Контекстное меню --------------------------------------------------

    def _build_menu(self):
        """Строит меню по текущему состоянию DNS-сервера"""
        import pystray
        running = self._app.engine.running

        return pystray.Menu(
            pystray.MenuItem(
                ">  Запустить DNS" if not running else "v  Запущен",
                self._action_start,
                enabled=not running,
            ),
            pystray.MenuItem(
                "■  Остановить" if running else "o  Остановлен",
                self._action_stop,
                enabled=running,
            ),
            pystray.MenuItem(
                ">>>  Перезапустить",
                self._action_restart,
                enabled=running,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                ">>>  Показать окно",
                self._action_show,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                ">>>  Выход",
                self._action_exit,
            ),
        )

    def _action_start(self):
        self._app.after(0, self._app.ctrl._start)

    def _action_stop(self):
        self._app.after(0, self._app.ctrl._stop)

    def _action_restart(self):
        self._app.after(0, self._app.ctrl._restart)

    def _action_show(self):
        self._app.after(0, self._show_window)

    def _action_exit(self):
        # Полный выход: останавливаем DNS, сбрасываем системный DNS, закрываем.
        if hasattr(self._app, '_quit_app'):
            self._app.after(0, self._app._quit_app)
        elif hasattr(self._app, '_on_close'):
            self._app.after(0, self._app._on_close)
        else:
            self._app.after(0, self._app.destroy)

    def _show_window(self):
        self._app.deiconify()
        self._app.lift()
        self._app.focus_force()

    # --- Публичные методы (вызываются из gui.py) ---------------------------

    def start(self):
        """Запускает иконку трея в фоновом потоке"""
        if self._thread and self._thread.is_alive():
            return  # уже работает
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log.info("Системный трей запущен")

    def stop(self):
        """Останавливает иконку трея и ждёт завершения потока.

        Ждём поток, чтобы Windows успел убрать иконку из трея — иначе
        остаётся «мёртвый» кружок, который исчезает только при наведении.
        """
        icon = self._icon
        if icon:
            try:
                icon.visible = False
            except Exception:
                pass
            try:
                icon.stop()
            except Exception:
                pass
            self._icon = None
        # Дожидаемся, пока поток трея реально завершится (с таймаутом).
        thread = self._thread
        if thread and thread.is_alive():
            try:
                thread.join(timeout=3)
            except Exception:
                pass
        self._thread = None
        log.info("Системный трей остановлен")

    def set_running(self):
        """Зелёная иконка - сервер работает"""
        self._update_icon(self._img_running, "NetDocker - DNS работает")

    def set_stopped(self):
        """Красная иконка - сервер остановлен"""
        self._update_icon(self._img_stopped, "NetDocker - DNS остановлен")

    def set_waiting(self, message="NetDocker - Ожидание..."):
        """Жёлтая иконка - промежуточное состояние (перезапуск, загрузка)"""
        self._update_icon(self._img_waiting, message)

    def notify(self, message, title="NetDocker"):
        """Показывает всплывающее уведомление (баллон) из трея, если поддерживается."""
        icon = self._icon
        if icon is None:
            return
        try:
            icon.notify(message, title)
        except Exception as e:
            log.debug("notify не поддерживается: %s", e)

    # --- Внутреннее --------------------------------------------------------

    def _update_icon(self, img, title):
        """Меняет иконку и тултип (можно вызывать из любого потока)"""
        icon = self._icon
        if icon is None:
            return
        try:
            icon.icon = img
            icon.title = title
            icon.menu = self._build_menu()
        except Exception as e:
            log.warning(f"Ошибка обновления трея: {e}")

    def _run(self):
        """Запускает pystray.Icon (свой event-loop) в этом потоке"""
        import pystray

        icon = pystray.Icon(
            "netdocker",
            self._img_stopped,
            "NetDocker - DNS остановлен",
            self._build_menu(),
        )
        self._icon = icon
        try:
            icon.run()
        finally:
            # Поток завершился — гарантированно сбрасываем ссылку,
            # чтобы не осталось «висящего» состояния иконки.
            self._icon = None
