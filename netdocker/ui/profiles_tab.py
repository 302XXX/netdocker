import base64
import ipaddress
import socket
import threading
import time
import tkinter as tk
from tkinter import messagebox
from urllib.parse import urlsplit

import requests
from dnslib import DNSRecord

from dns_server import save_config
from profile_utils import (
    BUILTIN_PROFILE_ID,
    MAX_USER_DNS_PROFILES,
    MAX_PROFILE_NAME_LEN,
    get_active_dns_profile,
    get_all_dns_profiles,
    get_profile_by_id,
    make_new_user_dns_profile,
)
from ui.common import ACCENT, BG, CARD, GREEN, INPUT_BG, PANEL, RED, SUBTEXT, TEXT, WHITE, YELLOW


class DnsProfilesTab(tk.Frame):
    def __init__(self, parent, engine, root_win, on_profile_changed=None, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.engine = engine
        self.root_win = root_win
        self.on_profile_changed = on_profile_changed
        self.selected_profile_id = self.engine.config.get("active_dns_profile", BUILTIN_PROFILE_ID)
        self._autosave_job = None
        self._autosave_suspend = False
        self._row_widgets = {}
        self._row_parents = {}
        self._user_empty_label = None
        self._ping_labels = {}
        # Состояние "пропинговать все":
        #   _ping_all_results[profile_id] = {"ok": bool, "latency_ms": int|None, "mode": "udp"|"doh"}
        #   _ping_all_best_id              = id профиля-победителя (или None)
        #   _ping_all_running              = идёт ли сейчас массовый пинг
        self._ping_all_results = {}
        self._ping_all_best_id = None
        self._ping_all_running = False
        self._ping_all_token = 0  # защита от устаревших результатов, если кликнули ещё раз
        self._build()
        self.refresh()

    def _build(self):
        main = tk.Frame(self, bg=BG)
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        left = tk.Frame(main, bg=BG, width=260)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        left.pack_propagate(False)

        right = tk.Frame(main, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))

        # «Пропинговать всё» — кликабельный контейнер из двух Label:
        #   - текст рисуется обычным "Segoe UI" (чёткий, читаемый, белый),
        #   - 📊 рисуется отдельным Label со шрифтом "Segoe UI Emoji" нужного размера.
        # Так смайл не «съезжает» и не превращается в моно-коробочку, как было,
        # когда весь текст рендерился одним шрифтом.
        self.btn_ping_all = tk.Frame(left, bg=BG, cursor="hand2")
        self.btn_ping_all.pack(fill=tk.X, pady=(0, 8))

        inner = tk.Frame(self.btn_ping_all, bg=BG)
        inner.pack(pady=8)

        self.btn_ping_all_text = tk.Label(
            inner,
            text="Пропинговать всё",
            bg=BG,
            fg=WHITE,
            font=("Segoe UI", 12, "bold"),
            cursor="hand2",
        )
        self.btn_ping_all_text.pack(side=tk.LEFT)

        self.btn_ping_all_emoji = tk.Label(
            inner,
            text="📊",
            bg=BG,
            fg=WHITE,
            font=("Segoe UI Emoji", 14),
            cursor="hand2",
            padx=6,
        )
        self.btn_ping_all_emoji.pack(side=tk.LEFT)

        for _w in (self.btn_ping_all, inner, self.btn_ping_all_text, self.btn_ping_all_emoji):
            _w.bind("<Button-1>", lambda _e: self._ping_all_profiles())

        built_card = tk.Frame(left, bg=CARD)
        built_card.pack(fill=tk.X, pady=(0, 8))
        tk.Label(built_card, text="🧩  Встроенный профиль", bg=CARD, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 8))
        self.builtin_rows = tk.Frame(built_card, bg=CARD)
        self.builtin_rows.pack(fill=tk.X, padx=10, pady=(0, 10))

        user_card = tk.Frame(left, bg=CARD)
        user_card.pack(fill=tk.BOTH, expand=True)
        tk.Label(user_card, text="🗂  Пользовательские DNS", bg=CARD, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=12, pady=(10, 8))
        self.user_rows = tk.Frame(user_card, bg=CARD)
        self.user_rows.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        edit_card = tk.Frame(right, bg=CARD)
        edit_card.pack(fill=tk.BOTH, expand=True)
        tk.Label(edit_card, text="⚙  Параметры профиля", bg=CARD, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, padx=14, pady=(10, 8))

        form = tk.Frame(edit_card, bg=CARD)
        form.pack(fill=tk.X, padx=14, pady=(0, 8))

        self.name_var = tk.StringVar()
        self.ipv4_primary_var = tk.StringVar()
        self.ipv4_secondary_var = tk.StringVar()
        self.ipv6_primary_var = tk.StringVar()
        self.ipv6_secondary_var = tk.StringVar()
        self.doh_url_var = tk.StringVar()
        self.dnscrypt_stamp_var = tk.StringVar()

        self.entries = []

        header = tk.Frame(form, bg=CARD)
        header.pack(fill=tk.X, pady=(0, 4))
        tk.Label(header, text="", bg=CARD, fg=TEXT, width=18).pack(side=tk.LEFT)
        tk.Label(header, text="Данные", bg=CARD, fg=SUBTEXT,
                 font=("Segoe UI", 8, "bold"), anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(header, text="Пинг", bg=CARD, fg=SUBTEXT,
                 font=("Segoe UI", 8, "bold"), width=18, anchor=tk.W).pack(side=tk.RIGHT)

        rows = [
            ("name", "Имя профиля:", self.name_var, 28),
            ("ipv4_primary", "IPv4 основной:", self.ipv4_primary_var, 20),
            ("ipv4_secondary", "IPv4 дополнительный:", self.ipv4_secondary_var, 20),
            ("ipv6_primary", "IPv6 основной:", self.ipv6_primary_var, 34),
            ("ipv6_secondary", "IPv6 дополнительный:", self.ipv6_secondary_var, 34),
            ("doh_url", "DoH URL:", self.doh_url_var, 42),
            ("dnscrypt_stamp", "DNSCrypt sdns://:", self.dnscrypt_stamp_var, 42),
        ]
        for key, text, var, width in rows:
            row = tk.Frame(form, bg=CARD)
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=text, bg=CARD, fg=TEXT,
                     font=("Segoe UI", 9), width=18, anchor=tk.W).pack(side=tk.LEFT)
            entry = tk.Entry(row, textvariable=var, bg=INPUT_BG, fg=TEXT,
                             insertbackground=WHITE, relief=tk.FLAT,
                             disabledbackground=INPUT_BG, disabledforeground=TEXT,
                             font=("Consolas", 9), width=width)
            entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)
            self.entries.append(entry)
            ping_lbl = tk.Label(row, text="—", bg=CARD, fg=SUBTEXT,
                                font=("Consolas", 8), width=18, anchor=tk.W)
            ping_lbl.pack(side=tk.RIGHT, padx=(8, 0))
            self._ping_labels[key] = ping_lbl

        tk.Label(
            edit_card,
            text=(
                "Выбор квадратика слева делает профиль активным.\n"
                "Активный профиль используется в главном меню и DNS-логике программы."
            ),
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 8),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, padx=14, pady=(0, 10))

        controls = tk.Frame(edit_card, bg=CARD)
        controls.pack(fill=tk.X, padx=14, pady=(0, 8))
        icon_gap = (0, 10)

        self.btn_add = tk.Label(controls, text="➕", bg=CARD, fg=GREEN,
                                font=("Segoe UI Emoji", 13), cursor="hand2")
        self.btn_add.pack(side=tk.LEFT, padx=icon_gap)
        self.btn_add.bind("<Button-1>", lambda _e: self._add_profile())

        self.btn_remove = tk.Label(controls, text="❌", bg=CARD, fg=RED,
                                   font=("Segoe UI Emoji", 13), cursor="hand2")
        self.btn_remove.pack(side=tk.LEFT, padx=icon_gap)
        self.btn_remove.bind("<Button-1>", lambda _e: self._remove_profile())

        self.btn_clone = tk.Label(controls, text="📝", bg=CARD, fg=ACCENT,
                                  font=("Segoe UI Emoji", 13), cursor="hand2")
        self.btn_clone.pack(side=tk.LEFT, padx=icon_gap)
        self.btn_clone.bind("<Button-1>", lambda _e: self._clone_profile())

        self.btn_ping = tk.Label(controls, text="🔄️", bg=CARD, fg=YELLOW,
                                 font=("Segoe UI Emoji", 13), cursor="hand2")
        self.btn_ping.pack(side=tk.LEFT, padx=icon_gap)
        self.btn_ping.bind("<Button-1>", lambda _e: self._ping_profile())

        self.status_lbl = tk.Label(edit_card, text="", bg=CARD, fg=SUBTEXT,
                                   font=("Segoe UI", 8), justify=tk.LEFT)
        self.status_lbl.pack(anchor=tk.W, padx=14, pady=(0, 12))

        # Жёсткое ограничение длины имени прямо при вводе (1..MAX_PROFILE_NAME_LEN).
        self.name_var.trace_add("write", self._cap_name_length)

        for var in (
            self.name_var,
            self.ipv4_primary_var,
            self.ipv4_secondary_var,
            self.ipv6_primary_var,
            self.ipv6_secondary_var,
            self.doh_url_var,
            self.dnscrypt_stamp_var,
        ):
            var.trace_add("write", self._schedule_autosave)

        self.entry_by_key = {
            "name": self.entries[0],
            "ipv4_primary": self.entries[1],
            "ipv4_secondary": self.entries[2],
            "ipv6_primary": self.entries[3],
            "ipv6_secondary": self.entries[4],
            "doh_url": self.entries[5],
            "dnscrypt_stamp": self.entries[6],
        }

    def _set_status(self, text, color=SUBTEXT):
        self.status_lbl.config(text=text, fg=color)

    @staticmethod
    def _set_icon_enabled(widget, enabled, color):
        widget.config(fg=(color if enabled else SUBTEXT), cursor=("hand2" if enabled else "arrow"))

    def _get_user_profiles(self):
        return list(self.engine.config.get("user_dns_profiles", []))

    @staticmethod
    def _is_valid_ip(value, version):
        value = str(value).strip()
        if not value:
            return True
        try:
            ip = ipaddress.ip_address(value)
            return ip.version == version
        except Exception:
            return False

    @staticmethod
    def _is_valid_doh_url(value):
        value = str(value).strip()
        if not value:
            return True
        try:
            parts = urlsplit(value)
            return parts.scheme in ("http", "https") and bool(parts.netloc)
        except Exception:
            return False

    def _clear_field_marks(self):
        for entry in self.entries:
            entry.config(highlightthickness=0)

    def _mark_invalid_field(self, key):
        entry = self.entry_by_key.get(key)
        if entry is not None:
            entry.config(highlightthickness=1, highlightbackground=RED, highlightcolor=RED)

    def _cap_name_length(self, *_args):
        """Не даёт ввести имя длиннее MAX_PROFILE_NAME_LEN — лишнее отсекаем."""
        value = self.name_var.get()
        if len(value) > MAX_PROFILE_NAME_LEN:
            self.name_var.set(value[:MAX_PROFILE_NAME_LEN])

    def _validate_current_form(self):
        self._clear_field_marks()

        data = {
            "name": self.name_var.get().strip(),
            "ipv4_primary": self.ipv4_primary_var.get().strip(),
            "ipv4_secondary": self.ipv4_secondary_var.get().strip(),
            "ipv6_primary": self.ipv6_primary_var.get().strip(),
            "ipv6_secondary": self.ipv6_secondary_var.get().strip(),
            "doh_url": self.doh_url_var.get().strip(),
            "dnscrypt_stamp": self.dnscrypt_stamp_var.get().strip(),
        }

        if not data["name"]:
            self._mark_invalid_field("name")
            return False, "Имя профиля не может быть пустым", "name", True

        if len(data["name"]) > MAX_PROFILE_NAME_LEN:
            self._mark_invalid_field("name")
            return False, f"Имя профиля — не больше {MAX_PROFILE_NAME_LEN} символов", "name", True

        if not self._is_valid_ip(data["ipv4_primary"], 4):
            self._mark_invalid_field("ipv4_primary")
            return False, "Некорректный IPv4 основной", "ipv4_primary", False

        if not self._is_valid_ip(data["ipv4_secondary"], 4):
            self._mark_invalid_field("ipv4_secondary")
            return False, "Некорректный IPv4 дополнительный", "ipv4_secondary", False

        if not self._is_valid_ip(data["ipv6_primary"], 6):
            self._mark_invalid_field("ipv6_primary")
            return False, "Некорректный IPv6 основной", "ipv6_primary", False

        if not self._is_valid_ip(data["ipv6_secondary"], 6):
            self._mark_invalid_field("ipv6_secondary")
            return False, "Некорректный IPv6 дополнительный", "ipv6_secondary", False

        if not self._is_valid_doh_url(data["doh_url"]):
            self._mark_invalid_field("doh_url")
            return False, "Некорректный DoH URL", "doh_url", False

        if data["dnscrypt_stamp"] and not data["dnscrypt_stamp"].startswith("sdns://"):
            self._mark_invalid_field("dnscrypt_stamp")
            return False, "DNSCrypt-штамп должен начинаться с sdns://", "dnscrypt_stamp", False

        is_empty_profile = not any(
            data[key] for key in ("ipv4_primary", "ipv4_secondary", "ipv6_primary",
                                  "ipv6_secondary", "doh_url", "dnscrypt_stamp")
        )
        if is_empty_profile:
            return True, "Профиль пустой: его можно хранить, но нельзя сделать активным", None, True

        return True, "Профиль валиден", None, False

    def _render_profile_row(self, parent, profile, active_id, selected_id):
        selected = profile["id"] == selected_id
        active = profile["id"] == active_id
        row_bg = PANEL if selected else CARD
        # highlightthickness=1 заранее (с цветом row_bg = "невидимая" рамка),
        # чтобы при появлении/исчезновении зелёной рамки победителя
        # высота строки НЕ менялась и список не "прыгал".
        row = tk.Frame(
            parent, bg=row_bg,
            highlightthickness=1, highlightbackground=row_bg, highlightcolor=row_bg,
        )
        row.pack(fill=tk.X, pady=2)
        self._row_parents[profile["id"]] = parent
        # NOTE: font/weight у строк намеренно не меняется между состояниями —
        # иначе при переключении профилей пакер пересчитывает геометрию строки
        # и виджеты заметно "дёргаются" на 1 кадр.
        chk = tk.Button(row, text=("☑" if active else "☐"), width=2,
                        command=lambda p=profile["id"]: self._activate_profile(p),
                        bg=row_bg, fg=(GREEN if active else SUBTEXT),
                        activebackground=row_bg, activeforeground=(GREEN if active else WHITE),
                        relief=tk.FLAT, bd=0, cursor="hand2",
                        highlightthickness=0, takefocus=0,
                        font=("Segoe UI", 10, "bold"))
        chk.pack(side=tk.LEFT, padx=(4, 2), pady=4)
        # 🏆-слот: фикс. ширина 2, всегда виден (пустой пробел по умолчанию),
        # чтобы появление кубка не двигало имя профиля.
        trophy = tk.Label(row, text=" ", width=2, bg=row_bg, fg=YELLOW,
                          font=("Segoe UI Emoji", 10))
        trophy.pack(side=tk.LEFT, padx=(0, 2))
        # Пинг-метка справа: фикс. ширина, чтобы появление "12 мс" / "FAIL"
        # не "сжимало" имя профиля.
        ping_lbl = tk.Label(row, text="", width=7, bg=row_bg, fg=SUBTEXT,
                            font=("Consolas", 8), anchor=tk.E)
        ping_lbl.pack(side=tk.RIGHT, padx=(2, 6))
        btn = tk.Button(row, text=profile["name"], command=lambda p=profile["id"]: self._select_profile(p),
                        bg=row_bg, fg=WHITE if selected else TEXT,
                        activebackground=row_bg, activeforeground=WHITE,
                        relief=tk.FLAT, bd=0, cursor="hand2",
                        highlightthickness=0, takefocus=0,
                        anchor=tk.W, font=("Segoe UI", 9, "normal"))
        btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 4), pady=4)
        self._row_widgets[profile["id"]] = {
            "row": row, "chk": chk, "btn": btn,
            "trophy": trophy, "ping": ping_lbl,
        }

    def refresh(self):
        # Инкрементальный refresh: не уничтожаем все строки скопом
        # (это давало "рывок" при удалении профиля, потому что список
        # на 1 кадр схлопывался в ноль и потом пересобирался).
        # Удаляем только реально исчезнувшие строки, добавляем только новые,
        # а у остальных просто обновляем стили через _update_profile_row_styles().

        active_id = self.engine.config.get("active_dns_profile", BUILTIN_PROFILE_ID)
        profiles = get_all_dns_profiles(self.engine.config)

        if get_profile_by_id(self.engine.config, self.selected_profile_id) is None:
            self.selected_profile_id = active_id

        builtin_profiles = [p for p in profiles if p.get("builtin")]
        user_profiles = [p for p in profiles if not p.get("builtin")]

        wanted_ids = {p["id"] for p in profiles}
        wanted_parent = {}
        for p in builtin_profiles:
            wanted_parent[p["id"]] = self.builtin_rows
        for p in user_profiles:
            wanted_parent[p["id"]] = self.user_rows

        # 1) Удаляем только исчезнувшие строки (или те, что переехали в другую секцию).
        for profile_id in list(self._row_widgets.keys()):
            current_parent = self._row_parents.get(profile_id)
            if profile_id not in wanted_ids or current_parent is not wanted_parent.get(profile_id):
                widgets = self._row_widgets.pop(profile_id, None)
                self._row_parents.pop(profile_id, None)
                if widgets is not None:
                    try:
                        widgets["row"].destroy()
                    except Exception:
                        pass

        # 2) Плейсхолдер "нет пользовательских профилей" — создаём/удаляем точечно.
        if not user_profiles:
            if self._user_empty_label is None:
                self._user_empty_label = tk.Label(
                    self.user_rows, text="Нет пользовательских профилей",
                    bg=CARD, fg=SUBTEXT, font=("Segoe UI", 8),
                )
                self._user_empty_label.pack(anchor=tk.W, padx=6, pady=6)
        else:
            if self._user_empty_label is not None:
                try:
                    self._user_empty_label.destroy()
                except Exception:
                    pass
                self._user_empty_label = None

        # 3) Добавляем только реально новые строки, сохраняя нужный порядок.
        #    Если порядок существующих строк не меняется, pack новых в конец —
        #    дешёвая операция, и видимого "рывка" не даёт.
        for profile in builtin_profiles:
            if profile["id"] not in self._row_widgets:
                self._render_profile_row(self.builtin_rows, profile, active_id, self.selected_profile_id)
        for profile in user_profiles:
            if profile["id"] not in self._row_widgets:
                self._render_profile_row(self.user_rows, profile, active_id, self.selected_profile_id)

        # 4) Стили/тексты у всех оставшихся строк обновляем точечно.
        self._update_profile_row_styles()
        self._load_selected_profile_into_form()

        self._set_icon_enabled(self.btn_remove, not self._selected_is_builtin(), RED)
        self._set_icon_enabled(self.btn_add, len(user_profiles) < MAX_USER_DNS_PROFILES, GREEN)
        self._set_icon_enabled(self.btn_ping, True, YELLOW)
        self._set_icon_enabled(self.btn_clone, len(user_profiles) < MAX_USER_DNS_PROFILES, ACCENT)

    def _load_selected_profile_into_form(self):
        profile = get_profile_by_id(self.engine.config, self.selected_profile_id) or get_active_dns_profile(self.engine.config)
        readonly = bool(profile.get("builtin"))
        self._autosave_suspend = True
        # Замораживаем перерисовку на время массового обновления формы,
        # чтобы Tk не отрисовывал промежуточные состояния (это и давало "рывок").
        try:
            self.update_idletasks()
        except Exception:
            pass
        pairs = (
            (self.name_var, profile.get("name", "")),
            (self.ipv4_primary_var, profile.get("ipv4_primary", "")),
            (self.ipv4_secondary_var, profile.get("ipv4_secondary", "")),
            (self.ipv6_primary_var, profile.get("ipv6_primary", "")),
            (self.ipv6_secondary_var, profile.get("ipv6_secondary", "")),
            (self.doh_url_var, profile.get("doh_url", "")),
            (self.dnscrypt_stamp_var, profile.get("dnscrypt_stamp", "")),
        )
        # Меняем значения StringVar только если они реально изменились —
        # каждый set() триггерит trace, лишний _schedule_autosave и перерисовку Entry.
        for var, value in pairs:
            if var.get() != value:
                var.set(value)
        self._autosave_suspend = False

        # Снимаем выделение красным с полей при переключении профиля,
        # иначе после клика по другому профилю остаётся "красная рамка" от прошлого.
        self._clear_field_marks()

        state = "disabled" if readonly else "normal"
        for entry in self.entries:
            # Перестраиваем Entry только если состояние реально другое,
            # иначе на каждом клике все 6 полей зря перерисовываются.
            if str(entry.cget("state")) != state:
                entry.config(state=state)
        # Сбрасываем ping-лейблы только если они не в дефолтном состоянии.
        for lbl in self._ping_labels.values():
            if lbl.cget("text") != "—":
                lbl.config(text="—", fg=SUBTEXT)
        if readonly:
            self._set_status("Встроенный профиль доступен только для просмотра и выбора", SUBTEXT)
        else:
            self._set_status("Изменения пользовательского профиля сохраняются автоматически", SUBTEXT)

    def _update_profile_row_styles(self):
        active_id = self.engine.config.get("active_dns_profile", BUILTIN_PROFILE_ID)
        profiles = {p["id"]: p for p in get_all_dns_profiles(self.engine.config)}
        best_id = self._ping_all_best_id
        for profile_id, widgets in self._row_widgets.items():
            profile = profiles.get(profile_id)
            if profile is None:
                continue
            selected = profile_id == self.selected_profile_id
            active = profile_id == active_id
            is_best = profile_id == best_id
            row_bg = PANEL if selected else CARD
            chk_text = "☑" if active else "☐"
            chk_fg = GREEN if active else SUBTEXT
            chk_active_fg = GREEN if active else WHITE
            btn_text = profile.get("name", "")
            btn_fg = WHITE if selected else TEXT
            # Зелёная рамка вокруг строки-победителя; у остальных рамка цвета фона
            # (она там есть всегда, чтобы высота строки не менялась — см. _render_profile_row).
            border_color = GREEN if is_best else row_bg
            # Кубок только у победителя; у остальных — пробел той же ширины.
            trophy_text = "🏆" if is_best else " "

            # Точечно меняем только реально изменившиеся атрибуты —
            # это убирает "мерцание" / "рывок" интерфейса при переключении профиля.
            row_w = widgets["row"]
            if str(row_w.cget("bg")) != row_bg:
                row_w.config(bg=row_bg)
            if str(row_w.cget("highlightbackground")) != border_color:
                row_w.config(highlightbackground=border_color, highlightcolor=border_color)

            chk_w = widgets["chk"]
            if str(chk_w.cget("text")) != chk_text:
                chk_w.config(text=chk_text)
            if str(chk_w.cget("bg")) != row_bg:
                chk_w.config(bg=row_bg, activebackground=row_bg)
            if str(chk_w.cget("fg")) != chk_fg:
                chk_w.config(fg=chk_fg, activeforeground=chk_active_fg)

            btn_w = widgets["btn"]
            if str(btn_w.cget("text")) != btn_text:
                btn_w.config(text=btn_text)
            if str(btn_w.cget("bg")) != row_bg:
                btn_w.config(bg=row_bg, activebackground=row_bg)
            if str(btn_w.cget("fg")) != btn_fg:
                btn_w.config(fg=btn_fg)
            # Шрифт намеренно не трогаем (см. _render_profile_row):
            # смена bold↔normal меняет ширину текста и дёргает геометрию.

            trophy_w = widgets.get("trophy")
            if trophy_w is not None:
                if str(trophy_w.cget("bg")) != row_bg:
                    trophy_w.config(bg=row_bg)
                if str(trophy_w.cget("text")) != trophy_text:
                    trophy_w.config(text=trophy_text)

            ping_w = widgets.get("ping")
            if ping_w is not None:
                if str(ping_w.cget("bg")) != row_bg:
                    ping_w.config(bg=row_bg)
                ping_text, ping_fg = self._ping_label_for(profile_id)
                if str(ping_w.cget("text")) != ping_text:
                    ping_w.config(text=ping_text)
                if str(ping_w.cget("fg")) != ping_fg:
                    ping_w.config(fg=ping_fg)

    def _set_ping_all_btn_state(self, enabled, text, emoji):
        """Меняет текст/эмодзи/цвет «кнопки» пропинговать всё (на самом деле — двух Label).

        enabled=False делает её приглушённой (SUBTEXT) и без курсора-руки,
        enabled=True возвращает белый текст и cursor='hand2'.
        """
        color = WHITE if enabled else SUBTEXT
        cursor = "hand2" if enabled else "arrow"
        try:
            self.btn_ping_all_text.config(text=text, fg=color, cursor=cursor)
            self.btn_ping_all_emoji.config(text=emoji, fg=color, cursor=cursor)
            self.btn_ping_all.config(cursor=cursor)
        except Exception:
            pass

    def _reset_ping_all_state(self):
        """Сбрасывает результаты массового пинга (после add/clone/remove профиля)."""
        # Инкрементим token, чтобы устаревший фоновый поток (если он ещё жив)
        # не записал свои результаты поверх нового состояния.
        self._ping_all_token += 1
        self._ping_all_results = {}
        self._ping_all_best_id = None
        self._ping_all_running = False
        self._set_ping_all_btn_state(enabled=True, text="Пропинговать всё", emoji="📊")

    def _ping_label_for(self, profile_id):
        """Возвращает (text, fg) для пинг-лейбла строки профиля."""
        res = self._ping_all_results.get(profile_id)
        if res is None:
            # Пинг ещё не запускали или сейчас идёт массовый пинг и результата пока нет.
            if self._ping_all_running:
                return "…", SUBTEXT
            return "", SUBTEXT
        if res.get("ok") and res.get("latency_ms") is not None:
            return f"{res['latency_ms']} мс", GREEN if profile_id == self._ping_all_best_id else TEXT
        if res.get("skipped"):
            return "—", SUBTEXT
        return "FAIL", RED

    def _save_selected_user_profile(self):
        if self._selected_is_builtin():
            return False
        valid, msg, _field, _empty = self._validate_current_form()
        if not valid:
            self._set_status(msg, RED)
            return False
        profiles = self._get_user_profiles()
        changed = False
        for profile in profiles:
            if profile.get("id") == self.selected_profile_id:
                profile["name"] = self.name_var.get().strip() or profile.get("name") or "Новый профиль"
                profile["ipv4_primary"] = self.ipv4_primary_var.get().strip()
                profile["ipv4_secondary"] = self.ipv4_secondary_var.get().strip()
                profile["ipv6_primary"] = self.ipv6_primary_var.get().strip()
                profile["ipv6_secondary"] = self.ipv6_secondary_var.get().strip()
                profile["doh_url"] = self.doh_url_var.get().strip()
                profile["dnscrypt_stamp"] = self.dnscrypt_stamp_var.get().strip()
                changed = True
                break
        if not changed:
            return False
        cfg = dict(self.engine.config)
        cfg["user_dns_profiles"] = profiles
        save_config(cfg)
        self.engine.reload_config()
        if self.selected_profile_id == self.engine.config.get("active_dns_profile") and self.on_profile_changed:
            self.on_profile_changed()
        return True

    def _auto_save_now(self):
        self._autosave_job = None
        if self._autosave_suspend:
            return
        try:
            valid, msg, _field, is_empty = self._validate_current_form()
            if not valid:
                self._set_status(msg, RED)
                return
            if self._save_selected_user_profile():
                self._set_status(msg if is_empty else "Профиль сохранён. При необходимости перезапусти DNS.",
                                 YELLOW if is_empty else GREEN)
                self._update_profile_row_styles()
        except Exception as exc:
            self._set_status(f"Ошибка сохранения: {exc}", RED)

    def _schedule_autosave(self, *_args):
        if self._autosave_suspend or self._selected_is_builtin():
            return
        if self._autosave_job is not None:
            try:
                self.after_cancel(self._autosave_job)
            except Exception:
                pass
        self._set_status("Сохраняю профиль...", YELLOW)
        self._autosave_job = self.after(500, self._auto_save_now)

    def _selected_is_builtin(self) -> bool:
        """True, если выбранный профиль — встроенный (xbox-dns, comss.one и т.п.).
        Встроенные read-only: их нельзя редактировать/удалять, но можно активировать."""
        p = get_profile_by_id(self.engine.config, self.selected_profile_id)
        return bool(p and p.get("builtin"))

    def _select_profile(self, profile_id):
        if profile_id == self.selected_profile_id:
            # Клик по уже выбранному профилю — не делаем ничего,
            # иначе зря пересобираем форму и провоцируем "рывок".
            return
        self.selected_profile_id = profile_id
        # Сначала обновляем стили строк (быстро, локально),
        # затем форму (медленнее) — так визуально клик отзывается мгновенно.
        self._update_profile_row_styles()
        self._load_selected_profile_into_form()
        self._set_icon_enabled(self.btn_remove, not self._selected_is_builtin(), RED)

    def _activate_profile(self, profile_id):
        profile = get_profile_by_id(self.engine.config, profile_id)
        if profile is None:
            return

        selection_changed = profile_id != self.selected_profile_id
        if selection_changed:
            self.selected_profile_id = profile_id
            self._update_profile_row_styles()
            self._load_selected_profile_into_form()

        # Встроенные профили (xbox-dns, comss.one и т.п.) пред-валидированы и
        # доступны только для чтения — форму для них валидировать не нужно.
        # Валидируем форму только для пользовательских профилей.
        if not profile.get("builtin"):
            valid, msg, field, is_empty = self._validate_current_form()
            if not valid:
                self._set_status(f"Профиль нельзя активировать: {msg}", RED)
                return
            if is_empty:
                self._set_status("Пустой профиль нельзя сделать активным", RED)
                return

        cfg = dict(self.engine.config)
        cfg["active_dns_profile"] = profile_id
        save_config(cfg)
        self.engine.reload_config()
        if self.on_profile_changed:
            self.on_profile_changed()
        # После save/reload меняется только активный профиль (галочка ☑),
        # поэтому форму повторно перегружать не нужно — достаточно обновить стили строк.
        self._update_profile_row_styles()
        profile = get_active_dns_profile(self.engine.config)
        if self.engine.running and hasattr(self.root_win, "ctrl"):
            if messagebox.askyesno(
                "Профиль выбран",
                f"Активный профиль: {profile.get('name')}\n\nПерезапустить DNS сейчас?",
                parent=self,
            ):
                self.root_win.ctrl._restart()
        else:
            self._set_status(f"Активный профиль: {profile.get('name')}", GREEN)

    def _add_profile(self):
        profiles = self._get_user_profiles()
        if len(profiles) >= MAX_USER_DNS_PROFILES:
            messagebox.showwarning("Лимит", f"Можно создать максимум {MAX_USER_DNS_PROFILES} профилей.", parent=self)
            return
        new_profile = make_new_user_dns_profile(profiles)
        profiles.append(new_profile)
        cfg = dict(self.engine.config)
        cfg["user_dns_profiles"] = profiles
        save_config(cfg)
        self.engine.reload_config()
        self.selected_profile_id = new_profile["id"]
        # Прошлые результаты «Пропинговать все» больше неактуальны — у нас новый профиль.
        self._reset_ping_all_state()
        self.refresh()
        self._set_status("Создан новый пустой профиль", GREEN)

    def _clone_profile(self):
        profiles = self._get_user_profiles()
        if len(profiles) >= MAX_USER_DNS_PROFILES:
            messagebox.showwarning("Лимит", f"Можно создать максимум {MAX_USER_DNS_PROFILES} профилей.", parent=self)
            return

        source = get_profile_by_id(self.engine.config, self.selected_profile_id)
        if source is None:
            return

        existing_names = {p.get("name") for p in profiles}
        base_name = f"{source.get('name', 'Профиль')} (копия)"
        clone_name = base_name
        index = 2
        while clone_name in existing_names:
            clone_name = f"{base_name} {index}"
            index += 1

        cloned = make_new_user_dns_profile(profiles)
        cloned["name"] = clone_name
        cloned["ipv4_primary"] = source.get("ipv4_primary", "")
        cloned["ipv4_secondary"] = source.get("ipv4_secondary", "")
        cloned["ipv6_primary"] = source.get("ipv6_primary", "")
        cloned["ipv6_secondary"] = source.get("ipv6_secondary", "")
        cloned["doh_url"] = source.get("doh_url", "")
        cloned["dnscrypt_stamp"] = source.get("dnscrypt_stamp", "")

        profiles.append(cloned)
        cfg = dict(self.engine.config)
        cfg["user_dns_profiles"] = profiles
        save_config(cfg)
        self.engine.reload_config()
        self.selected_profile_id = cloned["id"]
        self._reset_ping_all_state()
        self.refresh()
        self._set_status(f"Создана копия профиля: {clone_name}", GREEN)

    def _remove_profile(self):
        if self._selected_is_builtin():
            return
        profile = get_profile_by_id(self.engine.config, self.selected_profile_id)
        if profile is None:
            return
        if not messagebox.askyesno(
            "Удалить профиль",
            f"Удалить профиль «{profile.get('name')}»?",
            parent=self,
        ):
            return
        profiles = [p for p in self._get_user_profiles() if p.get("id") != self.selected_profile_id]
        cfg = dict(self.engine.config)
        cfg["user_dns_profiles"] = profiles
        if cfg.get("active_dns_profile") == self.selected_profile_id:
            cfg["active_dns_profile"] = BUILTIN_PROFILE_ID
        save_config(cfg)
        self.engine.reload_config()
        self.selected_profile_id = cfg.get("active_dns_profile", BUILTIN_PROFILE_ID)
        # Удалённый профиль мог быть победителем — сбрасываем подсветку.
        self._reset_ping_all_state()
        if self.on_profile_changed:
            self.on_profile_changed()
        self.refresh()
        self._set_status("Профиль удалён", GREEN)

    @staticmethod
    def _probe_tcp_host(host, port=53, timeout=2.5):
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        address = (host, port, 0, 0) if family == socket.AF_INET6 else (host, port)
        try:
            t0 = time.perf_counter()
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(address)
            sock.close()
            return True, int((time.perf_counter() - t0) * 1000)
        except Exception:
            return False, None

    @staticmethod
    def _probe_doh(url, timeout=4.0):
        try:
            req = DNSRecord.question("google.com", "A")
            b64 = base64.urlsafe_b64encode(req.pack()).rstrip(b"=").decode()
            t0 = time.perf_counter()
            resp = requests.get(url, headers={"Accept": "application/dns-message"}, params={"dns": b64}, timeout=timeout)
            resp.raise_for_status()
            DNSRecord.parse(resp.content)
            return True, int((time.perf_counter() - t0) * 1000)
        except Exception:
            return False, None

    def _ping_all_profiles(self):
        """Пингует все профили параллельно в фоновом потоке и подсвечивает лучший.

        Метрика «лучшего» зависит от выбранного в главном меню режима:
          - "udp" → берём min пинг по IPv4 primary/secondary + IPv6 primary/secondary
          - "doh" → берём пинг по DoH URL
        Профили, у которых для выбранного режима нет ни одной заполненной записи,
        помечаются как "—" (skipped) и в выборе победителя не участвуют.
        """
        if self._ping_all_running:
            return

        mode = (self.engine.config.get("xbox_dns_mode") or "udp").lower()
        if mode not in ("udp", "doh"):
            mode = "udp"

        profiles = list(get_all_dns_profiles(self.engine.config))
        if not profiles:
            self._set_status("Нет профилей для пинга", YELLOW)
            return

        # Сбрасываем прошлые результаты и сразу показываем "…" у всех строк,
        # чтобы пользователь видел, что процесс пошёл.
        self._ping_all_token += 1
        token = self._ping_all_token
        self._ping_all_running = True
        self._ping_all_results = {}
        self._ping_all_best_id = None
        self._update_profile_row_styles()
        self._set_ping_all_btn_state(enabled=False, text="Пингую всё…", emoji="⏳")
        self._set_status(
            f"Пингую все профили ({'DoH' if mode == 'doh' else 'UDP'})…", YELLOW
        )

        def worker():
            threads = []
            results = {}
            results_lock = threading.Lock()

            def probe_one(p):
                pid = p["id"]
                if mode == "doh":
                    url = (p.get("doh_url") or "").strip()
                    if not url:
                        with results_lock:
                            results[pid] = {"ok": False, "latency_ms": None, "skipped": True, "mode": mode}
                        return
                    ok, latency = self._probe_doh(url)
                    with results_lock:
                        results[pid] = {"ok": ok, "latency_ms": latency, "skipped": False, "mode": mode}
                else:
                    candidates = [
                        (p.get("ipv4_primary") or "").strip(),
                        (p.get("ipv4_secondary") or "").strip(),
                        (p.get("ipv6_primary") or "").strip(),
                        (p.get("ipv6_secondary") or "").strip(),
                    ]
                    candidates = [c for c in candidates if c]
                    if not candidates:
                        with results_lock:
                            results[pid] = {"ok": False, "latency_ms": None, "skipped": True, "mode": mode}
                        return
                    best_latency = None
                    any_ok = False
                    for host in candidates:
                        ok, latency = self._probe_tcp_host(host)
                        if ok and latency is not None:
                            any_ok = True
                            if best_latency is None or latency < best_latency:
                                best_latency = latency
                    with results_lock:
                        results[pid] = {
                            "ok": any_ok,
                            "latency_ms": best_latency,
                            "skipped": False,
                            "mode": mode,
                        }

            for p in profiles:
                t = threading.Thread(target=probe_one, args=(p,), daemon=True)
                t.start()
                threads.append(t)
            for t in threads:
                t.join()

            # Возвращаемся в UI-поток через after().
            self.after(0, lambda: self._on_ping_all_done(token, results, mode))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ping_all_done(self, token, results, mode):
        # Если за время пинга пользователь успел запустить ещё один — игнорируем старый.
        if token != self._ping_all_token:
            return
        self._ping_all_running = False
        self._ping_all_results = results

        # Выбираем победителя: только из тех, у кого ok=True и есть latency.
        best_id = None
        best_latency = None
        for pid, r in results.items():
            if r.get("ok") and r.get("latency_ms") is not None:
                if best_latency is None or r["latency_ms"] < best_latency:
                    best_latency = r["latency_ms"]
                    best_id = pid
        self._ping_all_best_id = best_id

        self._set_ping_all_btn_state(enabled=True, text="Пропинговать всё", emoji="📊")
        self._update_profile_row_styles()

        if best_id is None:
            self._set_status(
                f"Ни один профиль не ответил по режиму {'DoH' if mode == 'doh' else 'UDP'}",
                RED,
            )
        else:
            profiles = {p["id"]: p for p in get_all_dns_profiles(self.engine.config)}
            best_name = profiles.get(best_id, {}).get("name", "?")
            self._set_status(
                f"🏆 Самый быстрый: {best_name} — {best_latency} мс "
                f"(режим {'DoH' if mode == 'doh' else 'UDP'})",
                GREEN,
            )

    def _ping_profile(self):
        profile = get_profile_by_id(self.engine.config, self.selected_profile_id)
        if profile is None:
            return

        checks = [
            ("ipv4_primary", profile.get("ipv4_primary"), False),
            ("ipv4_secondary", profile.get("ipv4_secondary"), False),
            ("ipv6_primary", profile.get("ipv6_primary"), False),
            ("ipv6_secondary", profile.get("ipv6_secondary"), False),
            ("doh_url", profile.get("doh_url"), True),
        ]

        has_any = False
        for key, value, is_doh in checks:
            if not value:
                self._ping_labels[key].config(text="не задан", fg=SUBTEXT)
                continue
            has_any = True
            if is_doh:
                ok, latency = self._probe_doh(value)
            else:
                ok, latency = self._probe_tcp_host(value)
            text = f"{'OK' if ok else 'FAIL'}{'  ' + str(latency) + ' мс' if latency is not None else ''}"
            self._ping_labels[key].config(text=text, fg=(GREEN if ok else RED))

        if not has_any:
            self._set_status("В профиле нет заполненных адресов для проверки", YELLOW)
        else:
            self._set_status("Проверка профиля завершена", GREEN)
