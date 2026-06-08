import logging
import threading
import tkinter as tk
from tkinter import messagebox

from dns_server import save_config
from process_monitor import is_admin, reset_dns_to_auto, set_dns_to_localhost
from profile_utils import get_active_dns_profile
from ui.common import (
    ACCENT,
    BG,
    BORDER,
    CARD,
    GREEN,
    INPUT_BG,
    PANEL,
    PRESETS,
    SERVICE_CATEGORIES,
    RED,
    SUBTEXT,
    TEXT,
    WHITE,
    YELLOW,
    copy_to_clipboard,
    flat_btn,
    separator,
)
from ui.dialogs import ProcessPickerDialog, SettingsWindow, TestWindow

log = logging.getLogger("NetDocker.GUI")

# Иконки для известных сервисов (ключи совпадают с PRESETS из ui/common.py).
SERVICE_ICONS = {
    "ChatGPT / OpenAI": "🤖",
    "Claude (Anthropic)": "🧠",
    "Google Gemini": "✨",
    "Grok (xAI)": "🦾",
    "Perplexity": "🔮",
    "GitHub / Copilot": "🐙",
    "Modrinth": "🧱",
    "Spotify": "🎵",
    "Twitch": "🎮",
}

# Цвета иконок разделов (рисуем цветной кружок — эмодзи на Windows монохромны).
CATEGORY_COLORS = {
    "AI": "#5865f2",          # сине-фиолетовый
    "Разное": "#3ba55d",  # зелёный
    "Медиа": "#eb459e",       # розовый
}


class DnsModePanel(tk.Frame):
    """
    Панель настройки режима xbox-dns.ru:
      • DoH HTTPS — через https://xbox-dns.ru/dns-query (по умолчанию)
      • UDP DNS   — через IP активного профиля :53
    """

    def __init__(self, parent, engine, root_win, **kw):
        super().__init__(parent, bg=CARD, **kw)
        self.engine = engine
        self.root_win = root_win
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=CARD)
        hdr.pack(fill=tk.X, padx=14, pady=(12, 4))
        self.title_lbl = tk.Label(
            hdr,
            text="🛡  Активный DNS-профиль",
            bg=CARD,
            fg=WHITE,
            font=("Segoe UI", 11, "bold"),
        )
        self.title_lbl.pack(side=tk.LEFT)

        # Мини-иконка справа (в углу, противоположном щиту 🛡) — открывает
        # окно-справку «что делает каждый режим».
        self.mode_info_btn = tk.Label(
            hdr, text="ⓘ", bg=CARD, fg=ACCENT, cursor="hand2",
            font=("Segoe UI", 13, "bold"),
        )
        self.mode_info_btn.pack(side=tk.RIGHT)
        self.mode_info_btn.bind("<Button-1>", lambda _e: self._show_mode_help())

        separator(self, pady=4)

        self.mode_caption_lbl = tk.Label(
            self,
            text="Режим подключения активного профиля:",
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 9),
        )
        self.mode_caption_lbl.pack(anchor=tk.W, padx=14, pady=(4, 2))

        cfg = self.engine.config
        current_mode = cfg.get("xbox_dns_mode", "udp")
        self.mode_var = tk.StringVar(value=current_mode)

        self.frame_udp = tk.Frame(
            self,
            bg=CARD,
            bd=1,
            highlightthickness=1,
            highlightbackground=ACCENT if current_mode == "udp" else BORDER,
        )
        self.frame_udp.pack(fill=tk.X, padx=14, pady=(0, 4))

        tk.Radiobutton(
            self.frame_udp,
            text="⚡  UDP DNS  (быстрее, рекомендуется)",
            variable=self.mode_var,
            value="udp",
            command=self._on_mode_change,
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            highlightthickness=0, takefocus=0,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, padx=8, pady=(6, 2))

        self.udp_info_lbl = tk.Label(
            self.frame_udp,
            text="",
            bg=CARD,
            fg=SUBTEXT,
            font=("Consolas", 8),
            justify=tk.LEFT,
        )
        self.udp_info_lbl.pack(anchor=tk.W, padx=8, pady=(0, 6))

        self.frame_doh = tk.Frame(
            self,
            bg=CARD,
            bd=1,
            highlightthickness=1,
            highlightbackground=ACCENT if current_mode == "doh" else BORDER,
        )
        self.frame_doh.pack(fill=tk.X, padx=14, pady=(0, 6))

        tk.Radiobutton(
            self.frame_doh,
            text="🔒  DoH HTTPS  (если UDP блокируется)",
            variable=self.mode_var,
            value="doh",
            command=self._on_mode_change,
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            highlightthickness=0, takefocus=0,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, padx=8, pady=(6, 2))

        self.doh_info_lbl = tk.Label(
            self.frame_doh,
            text="",
            bg=CARD,
            fg=SUBTEXT,
            font=("Consolas", 8),
            justify=tk.LEFT,
        )
        self.doh_info_lbl.pack(anchor=tk.W, padx=8, pady=(0, 6))

        # ── DoT (DNS-over-TLS) ───────────────────────────────────────────────
        self.frame_dot = tk.Frame(
            self, bg=CARD, bd=1, highlightthickness=1,
            highlightbackground=ACCENT if current_mode == "dot" else BORDER,
        )
        self.frame_dot.pack(fill=tk.X, padx=14, pady=(0, 6))
        tk.Radiobutton(
            self.frame_dot,
            text="🔐  DoT  (DNS-over-TLS, порт 853)",
            variable=self.mode_var, value="dot", command=self._on_mode_change,
            bg=CARD, fg=TEXT, selectcolor=INPUT_BG, activebackground=CARD,
            highlightthickness=0, takefocus=0,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, padx=8, pady=(6, 2))
        self.dot_info_lbl = tk.Label(
            self.frame_dot, text="", bg=CARD, fg=SUBTEXT,
            font=("Consolas", 8), justify=tk.LEFT,
        )
        self.dot_info_lbl.pack(anchor=tk.W, padx=8, pady=(0, 6))

        # ── DoQ (DNS-over-QUIC) ──────────────────────────────────────────────
        self.frame_doq = tk.Frame(
            self, bg=CARD, bd=1, highlightthickness=1,
            highlightbackground=ACCENT if current_mode == "doq" else BORDER,
        )
        self.frame_doq.pack(fill=tk.X, padx=14, pady=(0, 6))
        tk.Radiobutton(
            self.frame_doq,
            text="🚀  DoQ  (DNS-over-QUIC, порт 853)",
            variable=self.mode_var, value="doq", command=self._on_mode_change,
            bg=CARD, fg=TEXT, selectcolor=INPUT_BG, activebackground=CARD,
            highlightthickness=0, takefocus=0,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, padx=8, pady=(6, 2))
        self.doq_info_lbl = tk.Label(
            self.frame_doq, text="", bg=CARD, fg=SUBTEXT,
            font=("Consolas", 8), justify=tk.LEFT,
        )
        self.doq_info_lbl.pack(anchor=tk.W, padx=8, pady=(0, 6))

        # ── DNSCrypt ─────────────────────────────────────────────────────────
        self.frame_dnscrypt = tk.Frame(
            self, bg=CARD, bd=1, highlightthickness=1,
            highlightbackground=ACCENT if current_mode == "dnscrypt" else BORDER,
        )
        self.frame_dnscrypt.pack(fill=tk.X, padx=14, pady=(0, 6))
        tk.Radiobutton(
            self.frame_dnscrypt,
            text="🔐  DNSCrypt  (свой sdns:// сервер)",
            variable=self.mode_var, value="dnscrypt", command=self._on_mode_change,
            bg=CARD, fg=TEXT, selectcolor=INPUT_BG, activebackground=CARD,
            highlightthickness=0, takefocus=0,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, padx=8, pady=(6, 2))
        self.dnscrypt_info_lbl = tk.Label(
            self.frame_dnscrypt, text="", bg=CARD, fg=SUBTEXT,
            font=("Consolas", 8), justify=tk.LEFT,
        )
        self.dnscrypt_info_lbl.pack(anchor=tk.W, padx=8, pady=(0, 6))

        separator(self, pady=4)

        self.addr_caption_lbl = tk.Label(
            self,
            text="Адреса активного профиля:",
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 9),
        )
        self.addr_caption_lbl.pack(anchor=tk.W, padx=14, pady=(0, 4))

        addr_card = tk.Frame(self, bg=INPUT_BG)
        addr_card.pack(fill=tk.X, padx=14, pady=(0, 6))

        self.addr_value_labels = {}
        rows = [
            ("IPv4 основной", "ipv4_primary"),
            ("IPv4 резервный", "ipv4_secondary"),
            ("IPv6 основной", "ipv6_primary"),
            ("IPv6 резервный", "ipv6_secondary"),
            ("DoH URL", "doh_url"),
        ]
        for label_text, key in rows:
            row = tk.Frame(addr_card, bg=INPUT_BG)
            row.pack(fill=tk.X, padx=8, pady=2)
            tk.Label(
                row,
                text=f"{label_text}:",
                bg=INPUT_BG,
                fg=SUBTEXT,
                font=("Segoe UI", 8),
                width=16,
                anchor=tk.W,
            ).pack(side=tk.LEFT)
            value_lbl = tk.Label(row, text="", bg=INPUT_BG, fg=GREEN, font=("Consolas", 8))
            value_lbl.pack(side=tk.LEFT)
            self.addr_value_labels[key] = value_lbl
            flat_btn(
                row,
                "📋",
                lambda k=key: copy_to_clipboard(self.root_win, self._current_profile.get(k, "")),
                bg=BORDER,
                fg=TEXT,
                padx=4,
                pady=1,
            ).pack(side=tk.RIGHT)

        separator(self, pady=4)

        btn_row = tk.Frame(self, bg=CARD)
        btn_row.pack(fill=tk.X, padx=14, pady=(0, 12))

        # Режим применяется сразу по клику на радиокнопку — кнопка «Сохранить»
        # не нужна. Оставляем только сброс DNS.
        flat_btn(btn_row, "🔄 Сброс DNS (DHCP)", self._reset, bg=SUBTEXT, fg=WHITE).pack(
            side=tk.LEFT
        )

        self._current_profile = get_active_dns_profile(self.engine.config)
        self.refresh_profile(self._current_profile)

        # При запуске активный режим уже применён и работает → зелёная рамка
        self._set_active_border(GREEN)

    def refresh_profile(self, profile=None):
        self._current_profile = profile or get_active_dns_profile(self.engine.config)
        profile = self._current_profile
        self.title_lbl.config(text=f"🛡  {profile.get('name')}")
        self.udp_info_lbl.config(
            text=(
                f"  Основной:   {profile.get('ipv4_primary') or '—'}\n"
                f"  Резервный:  {profile.get('ipv4_secondary') or '—'}"
            )
        )
        self.doh_info_lbl.config(text=f"  URL: {profile.get('doh_url') or 'не задан'}")
        dot_host = profile.get("dot_host") or profile.get("dot_ip") or "не задан"
        self.dot_info_lbl.config(
            text=f"  Сервер: {dot_host}:{profile.get('dot_port', 853)}"
        )
        # DoQ требует пакет aioquic — подсказываем, если он не установлен
        try:
            from dns_transports import doq_available
            doq_ready = doq_available()
        except Exception:
            doq_ready = False
        doq_host = profile.get("doq_host") or profile.get("doq_ip") or "не задан"
        if doq_ready:
            self.doq_info_lbl.config(
                text=f"  Сервер: {doq_host}:{profile.get('doq_port', 853)}"
            )
        else:
            self.doq_info_lbl.config(
                text="  ⚠ требуется: pip install aioquic"
            )
        # DNSCrypt: требует pynacl; показываем штамп профиля или подсказку
        try:
            from dnscrypt import dnscrypt_available
            dnscrypt_ready = dnscrypt_available()
        except Exception:
            dnscrypt_ready = False
        stamp = profile.get("dnscrypt_stamp") or ""
        if not dnscrypt_ready:
            self.dnscrypt_info_lbl.config(text="  ⚠ требуется: pip install pynacl")
        elif stamp:
            short = stamp[:34] + "…" if len(stamp) > 35 else stamp
            self.dnscrypt_info_lbl.config(text=f"  {short}")
        else:
            self.dnscrypt_info_lbl.config(
                text="  sdns:// штамп не задан (укажите в профиле)")
        for key, lbl in self.addr_value_labels.items():
            lbl.config(text=profile.get(key) or '—')

    def _mode_frames(self):
        return {
            "udp": self.frame_udp, "doh": self.frame_doh, "dot": self.frame_dot,
            "doq": self.frame_doq, "dnscrypt": self.frame_dnscrypt,
        }

    def _set_active_border(self, color):
        """Подсвечивает рамку АКТИВНОГО режима цветом-статусом, остальные — серым.
          ACCENT(синий)=выбран · YELLOW=применяется · GREEN=готово · RED=ошибка."""
        mode = self.mode_var.get()
        for m, frame in self._mode_frames().items():
            try:
                c = color if m == mode else BORDER
                frame.config(highlightbackground=c, highlightcolor=c)
            except Exception:
                pass

    def _update_mode_borders(self):
        # синяя рамка на активном режиме (нейтральное состояние)
        self._set_active_border(ACCENT)

    def _on_mode_change(self):
        """Клик по радиокнопке режима: применяем сразу, статус показываем
        ЦВЕТОМ рамки (жёлтая=применяется, зелёная=готово, красная=ошибка).
        Без всплывающих окон."""
        cfg = self.engine.config
        mode = self.mode_var.get()
        if cfg.get("xbox_dns_mode") == mode:
            self._set_active_border(GREEN)  # уже активен
            return

        # 🟡 жёлтая — идёт применение
        self._set_active_border(YELLOW)
        self.update_idletasks()

        def apply():
            ok, err = True, ""
            try:
                cfg["xbox_dns_mode"] = mode
                save_config(cfg)
                self.engine.reload_config()
            except Exception as exc:
                ok, err = False, str(exc)

            def done():
                if ok:
                    self._set_active_border(GREEN)   # 🟢 готово
                else:
                    self._set_active_border(RED)     # 🔴 ошибка
                    log.error(f"Не удалось применить режим {mode}: {err}")
            self.after(0, done)

        threading.Thread(target=apply, daemon=True).start()

    def _show_mode_help(self):
        """Окно-справка: что значит и делает каждый режим подключения."""
        win = tk.Toplevel(self)
        win.title("Режимы подключения — что выбрать")
        win.configure(bg=BG)
        win.geometry("520x560")
        win.minsize(520, 360)
        win.resizable(False, True)  # ширина закреплена — текст не съезжает
        win.transient(self.winfo_toplevel())
        try:
            win.grab_set()
        except Exception:
            pass

        tk.Label(win, text="🔌  Режимы подключения", bg=BG, fg=WHITE,
                 font=("Segoe UI", 14, "bold")).pack(anchor=tk.W, padx=18, pady=(16, 2))
        tk.Label(win, text="Все режимы дают доступ к одним и тем же сервисам — "
                 "разница в способе связи с DNS.",
                 bg=BG, fg=SUBTEXT, font=("Segoe UI", 9), wraplength=480,
                 justify=tk.LEFT).pack(anchor=tk.W, padx=18, pady=(0, 10))

        modes = [
            ("⚡  UDP DNS", ACCENT,
             "Обычный быстрый DNS по IP сервера (порт 53). Самый быстрый вариант. "
             "Минус: запрос не шифруется, провайдер видит, какие домены вы "
             "запрашиваете, и может его заблокировать."),
            ("🔒  DoH (DNS-over-HTTPS)", ACCENT,
             "DNS внутри обычного HTTPS (порт 443). Шифруется и маскируется под "
             "веб-трафик — провайдеру сложно отличить и заблокировать. "
             "Рекомендуется по умолчанию: работает по имени домена, не зависит "
             "от смены IP сервиса."),
            ("🔐  DoT (DNS-over-TLS)", ACCENT,
             "DNS внутри TLS на отдельном порту 853. Тоже шифрует запросы. "
             "Надёжно, но порт 853 провайдеру легче заметить, чем DoH."),
            ("🚀  DoQ (DNS-over-QUIC)", ACCENT,
             "DNS поверх QUIC (UDP, порт 853). Самый современный: быстрый и "
             "шифрованный, меньше задержек. Поддерживается не всеми серверами "
             "(нужен пакет aioquic)."),
            ("🗝  DNSCrypt", ACCENT,
             "Шифрованный протокол со своей криптографией и проверкой подлинности "
             "сервера. Для продвинутых: можно указать свой sdns:// сервер "
             "(AdGuard, Quad9 и др.) в профиле (нужен пакет pynacl)."),
        ]

        # Прокручиваемая область для карточек (фикс. ширина + колесо мыши)
        wrap = tk.Frame(win, bg=BG)
        wrap.pack(fill=tk.BOTH, expand=True, padx=18)
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, bd=0, width=484)
        vsb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        body = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=body, anchor="nw", width=466)

        def _sync(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        body.bind("<Configure>", _sync)

        def _wheel(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        win.bind("<Destroy>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        active_mode = self.engine.config.get("xbox_dns_mode", "udp")
        # код режима определяем по первому слову заголовка (UDP/DoH/DoT/DoQ/DNSCrypt)
        title_to_mode = {
            "UDP": "udp", "DoH": "doh", "DoT": "dot", "DoQ": "doq", "DNSCrypt": "dnscrypt",
        }
        for title, color, desc in modes:
            key = title.split()[1] if len(title.split()) > 1 else ""
            is_active = title_to_mode.get(key) == active_mode
            head_color = GREEN if is_active else ACCENT
            head_text = title + ("   ● сейчас активен" if is_active else "")
            card = tk.Frame(body, bg=CARD, bd=1, highlightthickness=1,
                            highlightbackground=(GREEN if is_active else BORDER))
            card.pack(fill=tk.X, pady=4)
            tk.Label(card, text=head_text, bg=CARD, fg=head_color,
                     font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=10, pady=(8, 2))
            tk.Label(card, text=desc, bg=CARD, fg=TEXT, font=("Segoe UI", 9),
                     wraplength=440, justify=tk.LEFT).pack(anchor=tk.W, padx=10, pady=(0, 8))

        tk.Label(win, text="💡 Не работает один режим — попробуйте другой. "
                 "Программа и сама переключается на запасной автоматически.",
                 bg=BG, fg=SUBTEXT, font=("Segoe UI", 8), wraplength=480,
                 justify=tk.LEFT).pack(anchor=tk.W, padx=18, pady=(8, 4))
        flat_btn(win, "Понятно", win.destroy, bg=ACCENT).pack(pady=(2, 14))

    def _reset(self):
        if not is_admin():
            messagebox.showerror("Ошибка", "Требуются права администратора")
            return
        ok, msg = reset_dns_to_auto()
        if ok:
            messagebox.showinfo("DNS сброшен", f"DNS возвращён на автополучение (DHCP)\n{msg}")
        else:
            messagebox.showerror("Ошибка", msg)


class RoutingList(tk.Frame):
    """Единый список маршрутизируемых объектов (домены + процессы)."""

    def __init__(self, parent, engine, root_win, **kw):
        super().__init__(parent, bg=CARD, **kw)
        self.engine = engine
        self.root_win = root_win
        self._build()
        self.refresh()

    def _build(self):
        # ── Блок «Сервисы» (разделы с тумблерами) ───────────────────────────
        svc_hdr = tk.Frame(self, bg=CARD)
        svc_hdr.pack(fill=tk.X, padx=14, pady=(12, 0))
        tk.Label(svc_hdr, text="🚀  Сервисы", bg=CARD, fg=WHITE,
                 font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT)
        tk.Label(
            self,
            text="Включите нужные — их сайты пойдут через обход, остальное напрямую.",
            bg=CARD, fg=SUBTEXT, font=("Segoe UI", 8), anchor="w", justify=tk.LEFT,
        ).pack(fill=tk.X, padx=14, pady=(0, 6))

        self._svc_rows = {}      # name -> {"canvas","state_lbl"}
        self._cat_widgets = {}   # category -> {"canvas","arrow","body","open"}
        svc_box = tk.Frame(self, bg=CARD)
        svc_box.pack(fill=tk.X, padx=14)
        for cat_name, services in SERVICE_CATEGORIES:
            self._build_category(svc_box, cat_name, services)

        separator(self, pady=6)

        # ── Заголовок-переключатель «Дополнительно» (список доменов вручную) ──
        self._adv_open = False
        hdr = tk.Frame(self, bg=CARD, cursor="hand2")
        hdr.pack(fill=tk.X, padx=14, pady=(0, 4))

        self._adv_toggle_lbl = tk.Label(
            hdr,
            text="▸  URL: список доменов (вручную)",
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        self._adv_toggle_lbl.pack(side=tk.LEFT)
        self.count_lbl = tk.Label(hdr, text="", bg=CARD, fg=SUBTEXT, font=("Segoe UI", 9))
        self.count_lbl.pack(side=tk.RIGHT)
        for w in (hdr, self._adv_toggle_lbl):
            w.bind("<Button-1>", lambda _e: self._toggle_advanced())

        # Контейнер, который сворачивается/разворачивается
        self._adv_box = tk.Frame(self, bg=CARD)
        # по умолчанию НЕ показываем (свёрнут)

        sf = tk.Frame(self._adv_box, bg=CARD)
        sf.pack(fill=tk.X, padx=14, pady=(0, 6))

        tk.Label(sf, text="🔍", bg=CARD, fg=SUBTEXT, font=("Segoe UI", 11)).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self.refresh())
        self.search_entry = tk.Entry(
            sf,
            textvariable=self.search_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, ipady=5)

        self.filter_var = tk.StringVar(value="all")
        for value, text in (("all", "Все"), ("domain", "Сайты"), ("process", "Программы")):
            tk.Radiobutton(
                sf,
                text=text,
                variable=self.filter_var,
                value=value,
                command=self.refresh,
                bg=CARD,
                fg=SUBTEXT,
                selectcolor=INPUT_BG,
                activebackground=CARD,
                font=("Segoe UI", 9),
            ).pack(side=tk.LEFT, padx=2)

        # ВАЖНО: нижние элементы (кнопки, добавление) пакуем СНИЗУ (side=BOTTOM)
        # ДО листбокса. Тогда tkinter сначала резервирует место под них, а
        # листбокс заполняет оставшуюся середину и при нехватке места сжимается
        # сам — кнопки «Удалить выбранное»/«Пресеты» никогда не уходят за край.
        btn_row = tk.Frame(self._adv_box, bg=CARD)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(4, 12))

        add_frame = tk.Frame(self._adv_box, bg=CARD)
        add_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(0, 6))

        # разделитель прямо над add_frame (тоже снизу)
        tk.Frame(self._adv_box, bg=BORDER, height=1).pack(
            side=tk.BOTTOM, fill=tk.X, pady=6)

        lf = tk.Frame(self._adv_box, bg=CARD)
        lf.pack(fill=tk.BOTH, expand=True, padx=14)

        sb = tk.Scrollbar(lf)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.lb = tk.Listbox(
            lf,
            yscrollcommand=sb.set,
            bg=INPUT_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=WHITE,
            font=("Consolas", 10),
            relief=tk.FLAT,
            bd=0,
            activestyle="none",
            height=6,
        )
        self.lb.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.lb.yview)
        self.lb.bind("<Delete>", lambda e: self._remove())

        self.entry = tk.Entry(
            add_frame,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, ipadx=6)
        self.entry.bind("<Return>", lambda e: self._add_typed())
        self.entry.insert(0, "chatgpt.com  или  chrome.exe")
        self.entry.bind("<FocusIn>", self._clear_hint)
        # Ctrl+C/V/X/A в русской раскладке включаются глобально
        # из gui.py через install_ru_clipboard_shortcuts_globally(root).

        self.type_var = tk.StringVar(value="domain")
        tk.Radiobutton(
            add_frame,
            text="Сайт",
            variable=self.type_var,
            value="domain",
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(8, 2))
        tk.Radiobutton(
            add_frame,
            text="Программа",
            variable=self.type_var,
            value="process",
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(0, 6))

        flat_btn(add_frame, "+ Добавить", self._add_typed, bg=GREEN).pack(side=tk.LEFT)

        btn_row = tk.Frame(self._adv_box, bg=CARD)
        btn_row.pack(fill=tk.X, padx=14, pady=(4, 12))

        flat_btn(btn_row, "🗑 Удалить выбранное", self._remove, bg=RED).pack(
            side=tk.LEFT,
            padx=(0, 6),
        )

        flat_btn(btn_row, "📚 Пресеты", self._show_preset_menu, bg=ACCENT).pack(
            side=tk.LEFT,
            padx=(0, 6),
        )

        flat_btn(btn_row, "⚙ Из запущенных...", self._pick_process, bg=BORDER, fg=TEXT).pack(
            side=tk.LEFT,
            padx=(0, 6),
        )

    # ── Сервисы (тумблеры) ───────────────────────────────────────────────────
    def _build_service_row(self, parent, name, domains):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill=tk.X, pady=3)

        icon = SERVICE_ICONS.get(name, "🌐")
        tk.Label(row, text=icon, bg=CARD, fg=TEXT, width=2,
                 font=("Segoe UI Emoji", 13)).pack(side=tk.LEFT)

        meta = tk.Frame(row, bg=CARD)
        meta.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 6))
        tk.Label(meta, text=name, bg=CARD, fg=TEXT, anchor="w",
                 font=("Segoe UI", 10, "bold")).pack(fill=tk.X)
        preview = ", ".join(domains[:2])
        if len(domains) > 2:
            preview += f" и ещё {len(domains) - 2}"
        tk.Label(meta, text=preview, bg=CARD, fg=SUBTEXT, anchor="w",
                 font=("Segoe UI", 8)).pack(fill=tk.X)

        state_lbl = tk.Label(row, text="", bg=CARD, fg=SUBTEXT,
                             font=("Segoe UI", 9), width=5, anchor="e")
        state_lbl.pack(side=tk.RIGHT, padx=(4, 0))

        # Тумблер на Canvas (рисуем дорожку + кружок)
        canvas = tk.Canvas(row, width=46, height=24, bg=CARD,
                           highlightthickness=0, bd=0, cursor="hand2")
        canvas.pack(side=tk.RIGHT)
        canvas.bind("<Button-1>", lambda _e, n=name: self._toggle_service(n))

        self._svc_rows[name] = {"canvas": canvas, "state_lbl": state_lbl}

    # ── Разделы (категории сервисов) ─────────────────────────────────────────
    def _build_category(self, parent, cat_name, services):
        # Контейнер раздела: и заголовок, и тело лежат ВНУТРИ него.
        # Благодаря этому тело при разворачивании всегда оказывается прямо
        # под своим заголовком, а другие разделы просто сдвигаются ниже.
        container = tk.Frame(parent, bg=CARD)
        container.pack(fill=tk.X, pady=(6, 0))

        # Заголовок раздела: стрелка ▸ + цветная иконка + имя + статус + тумблер
        header = tk.Frame(container, bg=CARD, cursor="hand2")
        header.pack(fill=tk.X)

        arrow = tk.Label(header, text="▸", bg=CARD, fg=ACCENT, width=2,
                         font=("Segoe UI", 11, "bold"), cursor="hand2")
        arrow.pack(side=tk.LEFT)

        # Цветная иконка раздела — СГЛАЖЕННЫЙ кружок (PIL), эмодзи на Windows
        # монохромны при fg, а Canvas-овал угловат. Поэтому рисуем через PIL.
        col = CATEGORY_COLORS.get(cat_name, ACCENT)
        icon_cv = tk.Canvas(header, width=16, height=16, bg=CARD,
                            highlightthickness=0, bd=0, cursor="hand2")
        self._draw_dot(icon_cv, col, size=16)
        icon_cv.pack(side=tk.LEFT, padx=(0, 6))

        name_lbl = tk.Label(header, text=cat_name, bg=CARD, fg=WHITE,
                            anchor="w", font=("Segoe UI", 10, "bold"),
                            cursor="hand2")
        name_lbl.pack(side=tk.LEFT)

        grp_canvas = tk.Canvas(header, width=46, height=24, bg=CARD,
                               highlightthickness=0, bd=0, cursor="hand2")
        grp_canvas.pack(side=tk.RIGHT, padx=(4, 0))
        grp_canvas.bind("<Button-1>",
                        lambda _e, c=cat_name: self._toggle_category(c))
        grp_state = tk.Label(header, text="", bg=CARD, fg=SUBTEXT,
                             font=("Segoe UI", 9), width=5, anchor="e")
        grp_state.pack(side=tk.RIGHT, padx=(4, 0))

        # тело раздела (внутри контейнера, свёрнуто по умолчанию)
        body = tk.Frame(container, bg=CARD)
        for svc in services:
            self._build_service_row(body, svc, PRESETS.get(svc, []))

        def _toggle(_e=None, c=cat_name):
            self._toggle_category_expand(c)
        # клик по заголовку/стрелке/иконке/имени разворачивает раздел
        for w in (header, arrow, icon_cv, name_lbl):
            w.bind("<Button-1>", _toggle)

        self._cat_widgets[cat_name] = {
            "canvas": grp_canvas, "arrow": arrow, "body": body,
            "state_lbl": grp_state, "services": services, "open": False,
        }

    def _toggle_category_expand(self, cat_name):
        w = self._cat_widgets.get(cat_name)
        if not w:
            return
        w["open"] = not w["open"]
        if w["open"]:
            w["body"].pack(fill=tk.X, padx=(14, 0))
            w["arrow"].config(text="▾")
        else:
            w["body"].pack_forget()
            w["arrow"].config(text="▸")

    def _category_state(self, services):
        """on — все сервисы раздела включены; off — ни один; part — часть."""
        flags = [self._service_enabled(PRESETS.get(s, [])) for s in services]
        if all(flags):
            return "on"
        if not any(flags):
            return "off"
        return "part"

    def _toggle_category(self, cat_name):
        w = self._cat_widgets.get(cat_name)
        if not w:
            return
        services = w["services"]
        state = self._category_state(services)
        # если включены все — выключаем все; иначе (off/part) — включаем все
        enable = state != "on"
        for svc in services:
            domains = PRESETS.get(svc, [])
            if enable:
                for d in domains:
                    self.engine.add_domain(d)
            else:
                for d in domains:
                    self.engine.remove_domain(d)
        self.refresh()

    def _refresh_categories(self):
        for cat_name, w in getattr(self, "_cat_widgets", {}).items():
            state = self._category_state(w["services"])
            self._draw_switch(w["canvas"], state)
            label = {"on": "вкл", "off": "выкл", "part": "часть"}[state]
            color = {"on": GREEN, "off": SUBTEXT, "part": YELLOW}[state]
            w["state_lbl"].config(text=label, fg=color)

    @staticmethod
    def _hex_rgb(value):
        value = value.lstrip("#")
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))

    def _draw_dot(self, canvas, color, size=16):
        """Рисует СГЛАЖЕННЫЙ цветной кружок (PIL supersampling).

        Canvas-овал угловат; чтобы кружок-иконка раздела был ровным, рисуем
        в 4× с PIL и уменьшаем. Картинку держим на canvas (иначе съест GC).
        """
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            # резерв: обычный (угловатый) овал
            canvas.delete("all")
            canvas.create_oval(2, 2, size - 2, size - 2, fill=color, outline=color)
            return
        scale = 4
        S = size * scale
        bg = self._hex_rgb(CARD)
        rgb = self._hex_rgb(color)
        img = Image.new("RGBA", (S, S), bg + (255,))
        draw = ImageDraw.Draw(img)
        m = 1 * scale
        draw.ellipse([m, m, S - m, S - m], fill=rgb)
        img = img.resize((size, size), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas._dot_img = photo

    def _draw_switch(self, canvas, state):
        """Рисует СГЛАЖЕННЫЙ тумблер через PIL (supersampling + LANCZOS).

        state: True/"on" — вкл (зелёный, кружок справа)
               False/"off" — выкл (серый, кружок слева)
               "part" — частично (жёлтый, кружок посередине)

        Tkinter Canvas не сглаживает овалы — края «лесенкой». Поэтому рисуем
        в 4× разрешении с PIL (антиалиасинг) и уменьшаем. PhotoImage держим на
        canvas, чтобы его не съел GC.
        """
        if state is True:
            state = "on"
        elif state is False:
            state = "off"

        w, h = 46, 24
        try:
            from PIL import Image, ImageDraw, ImageTk
        except Exception:
            return self._draw_switch_fallback(canvas, state)

        scale = 4
        W, H = w * scale, h * scale
        r = H // 2
        bg = self._hex_rgb(CARD)
        if state == "on":
            track, outline, thumb = GREEN, GREEN, WHITE
        elif state == "part":
            track, outline, thumb = YELLOW, YELLOW, WHITE
        else:
            track, outline, thumb = INPUT_BG, BORDER, SUBTEXT
        track = self._hex_rgb(track)
        outline = self._hex_rgb(outline)
        thumb = self._hex_rgb(thumb)

        img = Image.new("RGBA", (W, H), bg + (255,))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=r,
                               fill=track, outline=outline, width=scale)
        margin = 3 * scale
        d = H - 2 * margin
        if state == "on":
            cx = W - margin - d
        elif state == "part":
            cx = (W - d) // 2
        else:
            cx = margin
        draw.ellipse([cx, margin, cx + d, margin + d], fill=thumb)

        img = img.resize((w, h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=photo)
        canvas._switch_img = photo

    def _draw_switch_fallback(self, canvas, state):
        """Резерв без PIL — простой (угловатый) тумблер."""
        if state is True:
            state = "on"
        elif state is False:
            state = "off"
        canvas.delete("all")
        w, h = 46, 24
        if state == "on":
            track, outline, thumb = GREEN, GREEN, WHITE
        elif state == "part":
            track, outline, thumb = YELLOW, YELLOW, WHITE
        else:
            track, outline, thumb = INPUT_BG, BORDER, SUBTEXT
        r = h // 2
        canvas.create_oval(0, 0, h, h, fill=track, outline=outline)
        canvas.create_oval(w - h, 0, w, h, fill=track, outline=track)
        canvas.create_rectangle(r, 0, w - r, h, fill=track, outline=track)
        if state == "on":
            thumb_x = w - r
        elif state == "part":
            thumb_x = w // 2
        else:
            thumb_x = r
        tr = r - 3
        canvas.create_oval(thumb_x - tr, r - tr, thumb_x + tr, r + tr,
                           fill=thumb, outline=thumb)

    def _service_enabled(self, domains):
        """True, если ВСЕ домены сервиса сейчас в списке routed_domains."""
        current = {d.strip().lower() for d in self.engine.config.get("routed_domains", [])}
        return all(d.strip().lower() in current for d in domains)

    def _toggle_service(self, name):
        domains = PRESETS.get(name, [])
        if not domains:
            return
        if self._service_enabled(domains):
            for d in domains:
                self.engine.remove_domain(d)
        else:
            for d in domains:
                self.engine.add_domain(d)
        self.refresh()

    def _refresh_services(self):
        for name, widgets in getattr(self, "_svc_rows", {}).items():
            on = self._service_enabled(PRESETS.get(name, []))
            self._draw_switch(widgets["canvas"], on)
            widgets["state_lbl"].config(
                text="вкл" if on else "выкл",
                fg=GREEN if on else SUBTEXT,
            )
        self._refresh_categories()

    def _toggle_advanced(self):
        """Показывает/прячет ручной список доменов (раздел «Дополнительно»)."""
        self._adv_open = not self._adv_open
        if self._adv_open:
            self._adv_box.pack(fill=tk.BOTH, expand=True)
            self._adv_toggle_lbl.config(
                text="▾  URL: список доменов (вручную)", fg=TEXT)
        else:
            self._adv_box.pack_forget()
            self._adv_toggle_lbl.config(
                text="▸  URL: список доменов (вручную)", fg=SUBTEXT)

    def _clear_hint(self, _event):
        if self.entry.get() in ("chatgpt.com  или  chrome.exe", ""):
            self.entry.delete(0, tk.END)

    def _add_typed(self):
        raw = self.entry.get().strip()
        if not raw or raw == "chatgpt.com  или  chrome.exe":
            return

        kind = self.type_var.get()
        if kind == "domain":
            for prefix in ("https://", "http://", "www."):
                if raw.lower().startswith(prefix):
                    raw = raw[len(prefix):]
            raw = raw.split("/")[0].lower()
            self.engine.add_domain(raw)
        else:
            if "." not in raw:
                raw += ".exe"
            self.engine.add_process(raw)

        self.entry.delete(0, tk.END)
        self.refresh()

    def _remove(self):
        sel = self.lb.curselection()
        if not sel:
            return
        item = self.lb.get(sel[0])
        if item.startswith("🌐 "):
            self.engine.remove_domain(item[2:])
        elif item.startswith("⚙ "):
            self.engine.remove_process(item[2:])
        self.refresh()

    def _pick_process(self):
        dlg = ProcessPickerDialog(self.root_win)
        self.root_win.wait_window(dlg)
        if dlg.result:
            self.engine.add_process(dlg.result)
            self.refresh()

    def _show_preset_menu(self, btn):
        menu = tk.Menu(
            self.root_win,
            tearoff=0,
            bg=CARD,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground=WHITE,
            font=("Segoe UI", 9),
            bd=0,
        )
        for name, domains in PRESETS.items():
            menu.add_command(
                label=f"  {name}",
                command=lambda d=domains, n=name: self._apply_preset(n, d),
            )
        x = btn.winfo_rootx()
        y = btn.winfo_rooty() + btn.winfo_height()
        menu.tk_popup(x, y)

    def _apply_preset(self, name, domains):
        added = 0
        for domain in domains:
            if domain not in self.engine.config["routed_domains"]:
                self.engine.add_domain(domain)
                added += 1
        self.refresh()
        messagebox.showinfo("Пресет добавлен", f"'{name}'\nДобавлено доменов: {added}")

    def refresh(self):
        query = self.search_var.get().lower()
        filter_type = self.filter_var.get()
        cfg = self.engine.config

        items = []
        if filter_type in ("all", "domain"):
            for domain in cfg.get("routed_domains", []):
                if query in domain:
                    items.append(("domain", domain))
        if filter_type in ("all", "process"):
            for process in cfg.get("routed_processes", []):
                if query in process.lower():
                    items.append(("process", process))

        items.sort(key=lambda item: item[1])

        self.lb.delete(0, tk.END)
        for kind, value in items:
            icon = "🌐" if kind == "domain" else "⚙"
            self.lb.insert(tk.END, f"{icon} {value}")
            self.lb.itemconfig(tk.END, fg="#4a9eff" if kind == "domain" else "#f0a500")

        total_domains = len(cfg.get("routed_domains", []))
        total_processes = len(cfg.get("routed_processes", []))
        self.count_lbl.config(text=f"🌐 {total_domains} сайтов  ⚙ {total_processes} программ")

        # обновляем тумблеры сервисов под актуальный список доменов
        self._refresh_services()


class ControlBar(tk.Frame):
    def __init__(self, parent, engine, tray=None, **kw):
        super().__init__(parent, bg=PANEL, height=52, **kw)
        self.pack_propagate(False)
        self.engine = engine
        self.tray = tray
        self._build()

    def _build(self):
        self.btn_start = flat_btn(self, "▶  Запустить DNS", self._start, bg=GREEN)
        self.btn_start.pack(side=tk.LEFT, padx=(14, 6), pady=10)

        self.btn_stop = flat_btn(self, "■  Остановить", self._stop, bg=RED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 6), pady=10)
        self.btn_stop.config(state=tk.DISABLED)

        self.btn_restart = flat_btn(self, "🔄  Перезапустить DNS", self._restart, bg=YELLOW, fg=INPUT_BG)
        self.btn_restart.pack(side=tk.LEFT, padx=(0, 6), pady=10)
        self.btn_restart.config(state=tk.DISABLED)

        self.btn_settings = flat_btn(
            self,
            "⚙",
            self._settings,
            bg=PANEL,
            fg=SUBTEXT,
            padx=10,
            pady=4,
            font=("Segoe UI", 14),
        )
        self.btn_settings.pack(side=tk.RIGHT, padx=(0, 14), pady=10)

        self.status_lbl = tk.Label(
            self,
            text="⬤  Остановлен",
            bg=PANEL,
            fg=RED,
            font=("Segoe UI", 10, "bold"),
        )
        self.status_lbl.pack(side=tk.RIGHT, padx=(0, 4))

        self.admin_lbl = tk.Label(self, text="", bg=PANEL, fg=YELLOW, font=("Segoe UI", 9))
        self.admin_lbl.pack(side=tk.RIGHT, padx=8)
        if not is_admin():
            self.admin_lbl.config(text="⚠ Без прав администратора")

    def _start(self):
        # Защита от повторного запуска: если сервер уже работает — ничего не делаем
        # (просто фиксируем корректное состояние кнопок).
        if self.engine.running:
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.btn_restart.config(state=tk.NORMAL)
            return
        ok = self.engine.start()
        if ok:
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.btn_restart.config(state=tk.NORMAL)
            self.status_lbl.config(text="⬤  Работает  |  Режим NetDocker ✅", fg=GREEN)
            if self.tray:
                self.tray.set_running()

            if is_admin():
                def set_dns_bg():
                    cfg = self.engine.config
                    dns_ok, dns_msg, _ = set_dns_to_localhost(
                        fallback_ipv4=cfg.get("fallback_dns", "1.1.1.1"),
                        fallback_ipv6=cfg.get("fallback_dns6", ""),
                        enable_ipv6=cfg.get("enable_ipv6", True),
                    )
                    if not dns_ok:
                        log.warning(f"Автопереключение DNS не удалось: {dns_msg}")
                    self.after(300, self._show_start_toast)

                threading.Thread(target=set_dns_bg, daemon=True).start()
            else:
                self.status_lbl.config(
                    text="⬤  Работает  |  ⚠ Нужны права Администратора",
                    fg=YELLOW,
                )
                self.after(300, self._show_start_toast)
        else:
            reason = getattr(self.engine, "last_start_error", "") or (
                "Порт 53 занят или нет прав администратора."
            )
            messagebox.showerror(
                "Не удалось запустить DNS",
                f"Причина: {reason}\n\n"
                "Что попробовать:\n"
                "• Запустить NetDocker от имени администратора\n"
                "• Закрыть другой DNS (Pi-hole / AdGuard / второй NetDocker)\n"
                "• Проверить, не занят ли порт 53 системной службой",
            )

    def _show_start_toast(self):
        toast = tk.Toplevel(self)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg="#1e1e35")

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        width, height = 320, 80
        x = sw - width - 20
        y = sh - height - 50
        toast.geometry(f"{width}x{height}+{x}+{y}")

        frame = tk.Frame(toast, bg="#1e1e35", highlightbackground="#3ba55d", highlightthickness=2)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="🌐  NetDocker запущен",
            bg="#1e1e35",
            fg="#3ba55d",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor=tk.W, padx=12, pady=(10, 2))

        try:
            from profile_utils import get_active_dns_profile
            _prof = get_active_dns_profile(self.engine.config).get("name", "выбранный профиль")
        except Exception:
            _prof = "выбранный профиль"
        tk.Label(
            frame,
            text=f"Режим NetDocker активен — {_prof} работает",
            bg="#1e1e35",
            fg="#72767d",
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, padx=12)

        toast.attributes("-alpha", 0.0)

        def fade_in(alpha=0.0):
            alpha = min(alpha + 0.08, 1.0)
            toast.attributes("-alpha", alpha)
            if alpha < 1.0:
                toast.after(20, lambda: fade_in(alpha))

        def fade_out(alpha=1.0):
            alpha = max(alpha - 0.06, 0.0)
            toast.attributes("-alpha", alpha)
            if alpha > 0:
                toast.after(25, lambda: fade_out(alpha))
            else:
                toast.destroy()

        fade_in()
        toast.after(2800, lambda: fade_out())

    def _stop(self):
        self.engine.stop()
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_restart.config(state=tk.DISABLED)
        self.status_lbl.config(text="⬤  Остановлен", fg=RED)
        if self.tray:
            self.tray.set_stopped()

        if is_admin():
            threading.Thread(target=reset_dns_to_auto, daemon=True).start()

    def _restart(self):
        self.btn_restart.config(state=tk.DISABLED, text="🔄  Перезапуск...")
        self.status_lbl.config(text="⬤  Перезапуск...", fg=YELLOW)
        if self.tray:
            self.tray.set_waiting("NetDocker — Перезапуск...")
        self.engine.stop()
        self.after(500, self._restart_phase2)

    def _restart_phase2(self):
        ok = self.engine.start()
        if ok:
            self.btn_start.config(state=tk.DISABLED)
            self.btn_stop.config(state=tk.NORMAL)
            self.btn_restart.config(state=tk.NORMAL, text="🔄  Перезапустить DNS")
            self.status_lbl.config(text="⬤  Работает  |  Режим NetDocker ✅", fg=GREEN)
            if self.tray:
                self.tray.set_running()
            self.after(100, self._show_start_toast)
        else:
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self.btn_restart.config(state=tk.NORMAL, text="🔄  Перезапустить DNS")
            self.status_lbl.config(text="⬤  Остановлен (ошибка перезапуска)", fg=RED)
            if self.tray:
                self.tray.set_stopped()
            reason = getattr(self.engine, "last_start_error", "") or (
                "Порт 53 занят или нет прав администратора."
            )
            messagebox.showerror(
                "Не удалось перезапустить DNS",
                f"Причина: {reason}",
            )

    def _test(self):
        # Метод удален
        pass

    def _settings(self):
        SettingsWindow(self.winfo_toplevel(), self.engine)
