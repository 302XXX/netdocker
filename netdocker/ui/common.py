import tkinter as tk

# ── Цвета ────────────────────────────────────────────────────────────────────
BG        = "#12121f"
PANEL     = "#1a1a2e"
CARD      = "#1e1e35"
BORDER    = "#2e2e50"
ACCENT    = "#5865f2"
GREEN     = "#3ba55d"
RED       = "#ed4245"
YELLOW    = "#faa61a"
TEXT      = "#dcddde"
SUBTEXT   = "#72767d"
INPUT_BG  = "#0e0e1a"
WHITE     = "#ffffff"

XBOX_COLOR = "#107c10"   # зелёный Xbox

# ── Пресеты доменов ───────────────────────────────────────────────────────────
PRESETS = {
    "ChatGPT / OpenAI": [
        "openai.com", "chatgpt.com", "api.openai.com",
        "auth0.openai.com", "cdn.oaistatic.com", "chat.openai.com",
        "ab.chatgpt.com", "files.oaiusercontent.com",
        "sora.com", "sora.chatgpt.com",
    ],
    "Claude (Anthropic)": ["claude.ai", "anthropic.com", "api.anthropic.com"],
    "Google Gemini": ["gemini.google.com", "bard.google.com", "makersuite.google.com", "aistudio.google.com"],
    "Grok (xAI)": ["grok.com", "x.ai", "api.x.ai"],
    "Perplexity": ["perplexity.ai", "www.perplexity.ai"],
    "GitHub / Copilot": ["github.com", "copilot.github.com", "api.github.com", "github.githubassets.com", "githubcopilot.com"],
    "Modrinth": ["modrinth.com", "api.modrinth.com", "cdn.modrinth.com"],
    "Spotify": ["spotify.com", "open.spotify.com", "accounts.spotify.com", "api.spotify.com"],
    "Twitch": ["twitch.tv", "www.twitch.tv", "api.twitch.tv"],
}

# Сервисы сгруппированы по разделам. Порядок разделов и сервисов внутри —
# как они показываются в UI. Имена сервисов должны совпадать с ключами PRESETS.
SERVICE_CATEGORIES = [
    ("AI", ["ChatGPT / OpenAI", "Claude (Anthropic)", "Google Gemini", "Grok (xAI)", "Perplexity"]),
    ("Разное", ["GitHub / Copilot", "Modrinth"]),
    ("Медиа", ["Spotify", "Twitch"]),
]

# ── xbox-dns.ru Smart DNS ─────────────────────────────────────────────────────
# Адреса берём из единого источника правды (profile_utils), а не хардкодим.
from profile_utils import (
    XBOX_DNS_IPV4_PRIMARY as _XBOX_PRIMARY,
    XBOX_DNS_IPV4_SECONDARY as _XBOX_SECONDARY,
    XBOX_DOH_URL as _XBOX_DOH,
)

XBOX_DNS = {
    "primary": _XBOX_PRIMARY,
    "secondary": _XBOX_SECONDARY,
    "doh": _XBOX_DOH,
}


def flat_btn(parent, text, cmd, bg=ACCENT, fg=WHITE, padx=12, pady=6, **kw):
    # Позволяем переопределять шрифт и другие опции через **kw.
    # Иначе при передаче font=... из вызывающего кода tkinter получает
    # два значения для одного и того же аргумента и падает с TypeError.
    font = kw.pop("font", ("Segoe UI", 9, "bold"))
    return tk.Button(
        parent,
        text=text,
        command=cmd,
        bg=bg,
        fg=fg,
        activebackground=bg,
        activeforeground=fg,
        relief=tk.FLAT,
        bd=0,
        cursor="hand2",
        font=font,
        padx=padx,
        pady=pady,
        **kw,
    )



def separator(parent, color=BORDER, pady=6):
    frame = tk.Frame(parent, bg=color, height=1)
    frame.pack(fill=tk.X, pady=pady)
    return frame



def copy_to_clipboard(root, text):
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()


# ── Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A для русской раскладки ─────────────────
# Tk на Windows вешает встроенные шорткаты на keysym "c"/"v"/"x"/"a", которые
# приходят только в АНГЛИЙСКОЙ раскладке. В русской Tk видит keysym
# "Cyrillic_es"/"Cyrillic_em"/... — и шорткаты «не работают».
#
# Чинится привязкой к <Control-KeyPress> с проверкой keycode (физический
# код клавиши, не зависит от раскладки):
#     C=67, V=86, X=88, A=65, Z=90, Y=89
#
# Применять так:
#     enable_ru_clipboard_shortcuts(entry_widget)
# или передать сразу несколько:
#     enable_ru_clipboard_shortcuts(entry1, entry2, ...)

_RU_CLIPBOARD_KEYCODES = {
    67: "<<Copy>>",   # C
    86: "<<Paste>>",  # V
    88: "<<Cut>>",    # X
    65: "<<SelectAll>>",  # A (обработаем отдельно — нет встроенного <<SelectAll>> у Entry)
}


def _on_ru_clipboard_keypress(event):
    code = getattr(event, "keycode", 0)
    virtual = _RU_CLIPBOARD_KEYCODES.get(code)
    if virtual is None:
        return None
    widget = event.widget
    try:
        if virtual == "<<SelectAll>>":
            # У Entry: select_range(0, END). У Text: tag_add SEL 1.0 end.
            if isinstance(widget, tk.Entry):
                widget.select_range(0, tk.END)
                widget.icursor(tk.END)
            elif isinstance(widget, tk.Text):
                widget.tag_add(tk.SEL, "1.0", tk.END)
                widget.mark_set(tk.INSERT, "1.0")
                widget.see(tk.INSERT)
            else:
                return None
        else:
            widget.event_generate(virtual)
    except Exception:
        return None
    return "break"


def enable_ru_clipboard_shortcuts(*widgets):
    """Включает Ctrl+C/V/X/A в Entry/Text независимо от раскладки клавиатуры.

    Передавай любое число виджетов:
        enable_ru_clipboard_shortcuts(entry1, entry2, text_widget)

    Для приложения целиком удобнее вызвать один раз
    `install_ru_clipboard_shortcuts_globally(root)` — она навесит обработчик
    на классы Entry/Text и покроет даже те поля, которые будут созданы потом
    (в диалогах, popup-окнах и т.п.).
    """
    for w in widgets:
        if w is None:
            continue
        try:
            w.bind("<Control-KeyPress>", _on_ru_clipboard_keypress, add="+")
        except Exception:
            pass


def install_ru_clipboard_shortcuts_globally(root):
    """Один вызов — и Ctrl+C/V/X/A работают во всех Entry/Text приложения,
    в любой раскладке (RU/EN), включая виджеты в диалогах и popup-окнах,
    которые ещё не созданы.

    Работает через `bind_class("Entry", ...)` и `bind_class("Text", ...)` —
    в Tk это «глобальный» bind для всех виджетов данного класса.
    Вызывать один раз после создания root-окна.
    """
    try:
        root.bind_class("Entry", "<Control-KeyPress>", _on_ru_clipboard_keypress, add="+")
        root.bind_class("Text", "<Control-KeyPress>", _on_ru_clipboard_keypress, add="+")
        # ttk.Entry создаётся как класс "TEntry" — на всякий случай и его покрываем.
        root.bind_class("TEntry", "<Control-KeyPress>", _on_ru_clipboard_keypress, add="+")
        # Combobox внутри использует TEntry — но на случай если он своего класса:
        root.bind_class("TCombobox", "<Control-KeyPress>", _on_ru_clipboard_keypress, add="+")
    except Exception:
        # Если что-то пошло не так — fallback на per-widget bind ниже по коду.
        pass


# ── Слайдер с маркерами пресетов ─────────────────────────────────────────────
class PresetSlider(tk.Canvas):
    """Горизонтальный слайдер с подписанными маркерами пресетов.

    Параметры:
        parent     — родитель
        presets    — список (value:int, label:str), идущий по возрастанию value.
                     Маркеры этих пресетов рисуются равноудалёнными
                     (start / middle / end) — независимо от реальных значений.
                     Это даёт красивую визуальную шкалу, даже если значения
                     различаются на порядки (например 0 / 3600 / 86400).
        on_change  — callback(int_value), вызывается при перетаскивании
        width/height — размеры в пикселях
        snap_px    — порог snap-to-preset (пиксели). При попадании в этот
                     радиус от маркера значение фиксируется на нём, чтобы
                     "Stale TTL = 3600" получилось ровно, а не 3614.
    """

    TRACK_COLOR = BORDER
    TRACK_ACTIVE = ACCENT
    HANDLE_FILL = WHITE
    HANDLE_BORDER = ACCENT
    DOT_FILL = SUBTEXT
    DOT_FILL_HIT = ACCENT    # маркер, на котором сейчас стоит handle
    LABEL_COLOR = SUBTEXT

    PADDING_X = 14           # отступ слева/справа, чтобы handle не упирался в край
    TRACK_HEIGHT = 3
    DOT_RADIUS = 5
    HANDLE_RADIUS = 9

    def __init__(self, parent, presets, on_change, width=480, height=46, bg=None, **kw):
        if bg is None:
            bg = CARD
        super().__init__(
            parent, width=width, height=height,
            bg=bg, highlightthickness=0, bd=0, **kw,
        )
        self._bg = bg
        # Сортируем пресеты по value на случай если передали в произвольном порядке.
        self.presets = sorted(presets, key=lambda p: p[0])
        if len(self.presets) < 2:
            raise ValueError("PresetSlider требует минимум 2 пресета")
        self.on_change = on_change
        self._value = self.presets[0][0]
        self._suspend_callback = False
        self._dragging = False

        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", lambda _e: self._redraw())
        # Курсор-рука над всем слайдером — пользователь сразу видит что это интерактив.
        self.configure(cursor="hand2")

    # ── Внешний API ──────────────────────────────────────────────────────────
    def set_value(self, value, fire_callback=False):
        """Программно выставить значение (без вызова callback по умолчанию).

        Используется, когда слайдер должен подстроиться под значение,
        введённое пользователем в текстовое поле или применённое из пресета.
        """
        try:
            value = int(value)
        except Exception:
            return
        value = self._clamp(value)
        if value == self._value:
            self._redraw()
            return
        self._value = value
        self._redraw()
        if fire_callback and self.on_change and not self._suspend_callback:
            self.on_change(self._value)

    def get_value(self):
        return self._value

    # ── Внутренняя логика ────────────────────────────────────────────────────
    def _clamp(self, value):
        lo = self.presets[0][0]
        hi = self.presets[-1][0]
        return max(lo, min(hi, value))

    def _value_to_fraction(self, value):
        """Преобразует value -> [0..1] по СЕКЦИОННО ЛИНЕЙНОЙ шкале по пресетам.

        Пример для [(0,'A'),(3600,'B'),(86400,'C')]:
            0      → 0.0
            1800   → 0.25   (внутри секции A→B, посередине)
            3600   → 0.5
            45000  → ~0.75  (внутри секции B→C)
            86400  → 1.0
        """
        value = self._clamp(value)
        n = len(self.presets) - 1   # число секций
        for i in range(n):
            v_lo, _ = self.presets[i]
            v_hi, _ = self.presets[i + 1]
            if v_lo <= value <= v_hi:
                section_frac = (value - v_lo) / (v_hi - v_lo) if v_hi > v_lo else 0.0
                return (i + section_frac) / n
        return 1.0

    def _fraction_to_value(self, frac):
        frac = max(0.0, min(1.0, frac))
        n = len(self.presets) - 1
        scaled = frac * n
        i = int(scaled)
        if i >= n:
            return self.presets[-1][0]
        section_frac = scaled - i
        v_lo, _ = self.presets[i]
        v_hi, _ = self.presets[i + 1]
        return int(round(v_lo + section_frac * (v_hi - v_lo)))

    def _track_geometry(self):
        """Возвращает (x_left, x_right, y_center) — границы трека."""
        w = max(2 * self.PADDING_X + 20, int(self.winfo_width()))
        h = max(self.HANDLE_RADIUS * 2 + 12, int(self.winfo_height()))
        x_left = self.PADDING_X
        x_right = w - self.PADDING_X
        y_center = h // 2 - 4   # чуть выше центра, чтобы подписи внизу влезали
        return x_left, x_right, y_center

    def _x_for_value(self, value):
        x_left, x_right, _ = self._track_geometry()
        frac = self._value_to_fraction(value)
        return int(round(x_left + frac * (x_right - x_left)))

    def _value_for_x(self, x):
        x_left, x_right, _ = self._track_geometry()
        if x_right <= x_left:
            return self.presets[0][0]
        frac = (x - x_left) / (x_right - x_left)
        return self._fraction_to_value(frac)

    def _snap_value_if_near(self, value):
        """Если значение в пределах ~2% шкалы от маркера пресета — снапит к нему."""
        x_left, x_right, _ = self._track_geometry()
        if x_right <= x_left:
            return value
        x_current = self._x_for_value(value)
        snap_px = max(6, int((x_right - x_left) * 0.02))
        for v, _label in self.presets:
            if abs(x_current - self._x_for_value(v)) <= snap_px:
                return v
        return value

    # ── Отрисовка ────────────────────────────────────────────────────────────
    def _redraw(self):
        self.delete("all")
        x_left, x_right, y = self._track_geometry()

        # 1) сам трек (неактивная часть — серая)
        self.create_rectangle(
            x_left, y - self.TRACK_HEIGHT // 2,
            x_right, y + self.TRACK_HEIGHT // 2 + 1,
            fill=self.TRACK_COLOR, outline="",
        )

        # 2) активная часть (от начала до handle) — акцентным цветом
        x_handle = self._x_for_value(self._value)
        if x_handle > x_left:
            self.create_rectangle(
                x_left, y - self.TRACK_HEIGHT // 2,
                x_handle, y + self.TRACK_HEIGHT // 2 + 1,
                fill=self.TRACK_ACTIVE, outline="",
            )

        # 3) маркеры пресетов (3 точки) с подписями под ними
        h = int(self.winfo_height())
        label_y = min(h - 6, y + 14)
        for value, label in self.presets:
            x = self._x_for_value(value)
            # Если handle ровно на маркере — подсвечиваем его акцентным цветом.
            is_hit = (value == self._value)
            fill = self.DOT_FILL_HIT if is_hit else self.DOT_FILL
            r = self.DOT_RADIUS
            self.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline="")
            # Подпись под точкой. Если маркер у самого края — выравниваем по краю,
            # чтобы текст не вылез за пределы canvas.
            anchor = "n"
            tx = x
            if x - x_left < 30:
                anchor = "nw"
                tx = x - 4
            elif x_right - x < 30:
                anchor = "ne"
                tx = x + 4
            self.create_text(
                tx, label_y, text=label, fill=self.LABEL_COLOR,
                font=("Segoe UI", 8), anchor=anchor,
            )

        # 4) handle поверх всего
        r = self.HANDLE_RADIUS
        # белый круг с обводкой акцентного цвета — выглядит как "drag-кружок"
        self.create_oval(
            x_handle - r, y - r, x_handle + r, y + r,
            fill=self.HANDLE_FILL, outline=self.HANDLE_BORDER, width=2,
        )

    # ── Drag-логика ──────────────────────────────────────────────────────────
    def _on_press(self, event):
        self._dragging = True
        self._update_from_x(event.x)

    def _on_drag(self, event):
        if not self._dragging:
            return
        self._update_from_x(event.x)

    def _on_release(self, _event):
        self._dragging = False
        # На release ещё раз пробуем "прилипнуть" к пресету —
        # пользователь обычно отпускает чуть мимо маркера.
        snapped = self._snap_value_if_near(self._value)
        if snapped != self._value:
            self._value = snapped
            self._redraw()
            if self.on_change and not self._suspend_callback:
                self.on_change(self._value)

    def _update_from_x(self, x):
        value = self._value_for_x(x)
        value = self._snap_value_if_near(value)
        if value == self._value:
            return
        self._value = value
        self._redraw()
        if self.on_change and not self._suspend_callback:
            self.on_change(self._value)
