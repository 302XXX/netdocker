"""
NetDocker - GUI v2
Главный экран: список программ/сайтов + плашка DNS-режима.

Файл оставлен как точка входа GUI, а крупные виджеты и диалоги
вынесены в пакет ui/ для более удобной поддержки проекта.
"""

import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import requests

from dns_server import get_instance
from process_monitor import (
    IS_WINDOWS,
    flush_dns_cache,
    is_admin,
    reset_chrome_doh,
    reset_dns_to_auto,
    set_chrome_doh,
    set_dns_profile,
    set_dns_to_localhost,
    set_edge_doh,
)
from profile_utils import get_active_dns_profile
from tray_icon import TrayIcon
from ui.common import (
    ACCENT,
    BG,
    BORDER,
    CARD,
    GREEN,
    INPUT_BG,
    PANEL,
    RED,
    SUBTEXT,
    TEXT,
    WHITE,
    XBOX_COLOR,
    YELLOW,
    copy_to_clipboard,
    flat_btn,
    install_ru_clipboard_shortcuts_globally,
    separator,
)
from ui.panels import ControlBar, DnsModePanel, RoutingList
from ui.profiles_tab import DnsProfilesTab
from ui.query_log_tab import QueryLogTab


class NetDockerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("UmbraDNS")
        self.geometry("1060x780")
        # Нижние кнопки списка («Удалить выбранное», «Пресеты») закреплены снизу
        # (side=BOTTOM) — при нехватке места сжимается листбокс, а не кнопки.
        self.minsize(900, 720)
        self.configure(bg=BG)

        self.engine = get_instance()
        self._diag_refreshing = False

        # Состояние режима: 'blue', 'black', 'red'
        self.current_mode = tk.StringVar(value="blue")

        # Глобально включаем Ctrl+C / Ctrl+V / Ctrl+X / Ctrl+A во ВСЕХ полях
        # Entry/Text приложения — в любой раскладке (в русской встроенные
        # шорткаты Tk на Windows не работают). См. ui/common.py.
        install_ru_clipboard_shortcuts_globally(self)

        self.tray = TrayIcon(self)
        self.tray.start()

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Периодически проверяем, не просит ли вторая копия показать окно
        # (повторный запуск start.bat вместо плодения копий поднимает это окно).
        self.after(1000, self._poll_show_request)

        if not is_admin() and IS_WINDOWS:
            self.after(500, self._warn_admin)

    def _poll_show_request(self):
        try:
            from single_instance import consume_show_request
            if consume_show_request():
                self._restore_window()
        except Exception:
            pass
        finally:
            self.after(1000, self._poll_show_request)

    def _restore_window(self):
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.attributes("-topmost", True)
            self.after(300, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

    def _build(self):
        hdr = tk.Frame(self, bg="#0e0e1a", height=48)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text="🌐  UmbraDNS",
            bg="#0e0e1a",
            fg=WHITE,
            font=("Segoe UI", 15, "bold"),
        ).pack(side=tk.LEFT, padx=18)

        # Тумблер режимов (Визуал)
        mode_frame = tk.Frame(hdr, bg="#0e0e1a")
        mode_frame.pack(side=tk.LEFT, padx=20)

        def set_mode_fixed(mode, color):
            self.current_mode.set(mode)
            btn_blue.config(bg=ACCENT if mode == "blue" else "#0e0e1a")
            btn_black.config(bg=CARD if mode == "black" else "#0e0e1a")
            btn_red.config(bg=RED if mode == "red" else "#0e0e1a")
            
            # Синхронизируем с бекендом
            dpi_map = {"blue": "off", "black": "combo", "red": "zapret"}
            backend_mode = dpi_map.get(mode, "off")
            self.engine.set_dpi_mode(backend_mode)
            
            if hasattr(self, 'ctrl'):
                self.ctrl.update_mode_text(mode)

        # Создаем стилизованные кнопки-кружки
        def create_mode_btn(text, active_color):
            btn = tk.Label(
                mode_frame, 
                text=text, 
                bg="#0e0e1a", 
                fg=WHITE, 
                font=("Segoe UI Emoji", 14), 
                cursor="hand2",
                padx=8,
                pady=8
            )
            return btn

        btn_blue = create_mode_btn("🔵", ACCENT)
        btn_blue.pack(side=tk.LEFT, padx=4)
        btn_blue.bind("<Button-1>", lambda e: set_mode_fixed("blue", ACCENT))

        btn_black = create_mode_btn("⚫️", CARD)
        btn_black.pack(side=tk.LEFT, padx=4)
        btn_black.bind("<Button-1>", lambda e: set_mode_fixed("black", CARD))

        btn_red = create_mode_btn("🔴", RED)
        btn_red.pack(side=tk.LEFT, padx=4)
        btn_red.bind("<Button-1>", lambda e: set_mode_fixed("red", RED))
        
        # Чтобы первый режим был активен при запуске:
        set_mode_fixed("blue", ACCENT)

        # Возвращаем панель управления (Start/Stop/Restart)
        self.ctrl = ControlBar(self, self.engine, self.tray)
        self.ctrl.pack(fill=tk.X)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("App.TNotebook", background=BG, borderwidth=0, tabmargins=0)
        style.configure(
            "App.TNotebook.Tab",
            background=PANEL,
            foreground=SUBTEXT,
            padding=[16, 6],
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "App.TNotebook.Tab",
            background=[("selected", CARD)],
            foreground=[("selected", WHITE)],
        )

        self.nb = ttk.Notebook(self, style="App.TNotebook")
        self.nb.pack(fill=tk.BOTH, expand=True)
        self.nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        tab_main = tk.Frame(self.nb, bg=BG)
        self.nb.add(tab_main, text="  📋 Маршрутизация  ")
        self._build_main_tab(tab_main)

        self.tab_net = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.tab_net, text="  🔧 Сеть и диагностика  ")
        self._build_network_tab(self.tab_net)

        self.tab_profiles = tk.Frame(self.nb, bg=BG)
        self.nb.add(self.tab_profiles, text="  🧩 DNS-профили  ")
        self._build_profiles_tab(self.tab_profiles)

        # Новый «📊 Журнал» — структурированный Query Log с фильтрами/поиском/экспортом.
        # Старый «📋 Лог» (tail файла netdocker.log) удалён — он перекрывался
        # этим табом и был неудобен для дебага.
        self.query_log_tab = QueryLogTab(self.nb, self.engine)
        self.nb.add(self.query_log_tab, text="  📊 Журнал  ")


    def _build_main_tab(self, parent):
        main = tk.Frame(parent, bg=BG)
        main.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        left = tk.Frame(main, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.routing = RoutingList(left, self.engine, self)
        self.routing.pack(fill=tk.BOTH, expand=True)

        right = tk.Frame(main, bg=BG, width=360)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 0))
        right.pack_propagate(False)
        self.dns_panel = DnsModePanel(right, self.engine, self)
        self.dns_panel.pack(fill=tk.X)

    def _build_profiles_tab(self, parent):
        self.profiles_tab = DnsProfilesTab(parent, self.engine, self, on_profile_changed=self._refresh_profile_views)
        self.profiles_tab.pack(fill=tk.BOTH, expand=True)

    def _build_network_tab(self, parent):
        canvas = tk.Canvas(parent, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = tk.Frame(canvas, bg=BG)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_resize(event):
            canvas.itemconfig(win_id, width=event.width)

        canvas.bind("<Configure>", on_resize)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def on_wheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", on_wheel)

        p = inner

        self._net_section(p, "📡  Текущий DNS системы и апстримы")

        dns_card = tk.Frame(p, bg=CARD)
        dns_card.pack(fill=tk.X, padx=14, pady=(0, 6))

        self._diag_table_card = tk.Frame(dns_card, bg=INPUT_BG)
        self._diag_table_card.pack(fill=tk.X, padx=14, pady=(10, 10))
        self._diag_rows = {}
        self._build_diag_table()

        btn_row = tk.Frame(p, bg=BG)
        btn_row.pack(fill=tk.X, padx=14, pady=(0, 12))
        flat_btn(btn_row, "🔄 Обновить диагностику", self._refresh_dns_status, bg=BORDER, fg=TEXT).pack(
            side=tk.LEFT,
            padx=(0, 6),
        )
        flat_btn(btn_row, "📋 Скопировать отчёт", self._copy_diag_report, bg=ACCENT).pack(side=tk.LEFT, padx=(0, 6))
        self._leak_btn = flat_btn(btn_row, "🛡 Проверить утечку DNS", self._check_dns_leak, bg=BORDER, fg=TEXT)
        self._leak_btn.pack(side=tk.LEFT)

        self._net_section(p, "🌐  DoH активного профиля в браузер")

        browser_card = tk.Frame(p, bg=CARD)
        browser_card.pack(fill=tk.X, padx=14, pady=(0, 6))
        bc = tk.Frame(browser_card, bg=CARD)
        bc.pack(fill=tk.X, padx=14, pady=12)

        self._browser_doh_lbl = tk.Label(bc, text="", bg=CARD, fg="#4ecca3", font=("Consolas", 9))
        self._browser_doh_lbl.pack(anchor=tk.W, pady=(0, 8))

        row_b = tk.Frame(bc, bg=CARD)
        row_b.pack(fill=tk.X, pady=(0, 4))
        flat_btn(
            row_b,
            "🔵  Прописать DoH в Google Chrome",
            self._action_set_chrome_doh,
            bg="#1a73e8",
            padx=10,
        ).pack(side=tk.LEFT, padx=(0, 6))
        flat_btn(
            row_b,
            "🔷  Прописать DoH в Microsoft Edge",
            self._action_set_edge_doh,
            bg="#0078d4",
            padx=10,
        ).pack(side=tk.LEFT)

        self._browser_info_lbl = tk.Label(
            bc,
            text="",
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 8),
            justify=tk.LEFT,
        )
        self._browser_info_lbl.pack(anchor=tk.W, pady=(4, 4))

        self._browser_action_lbl = tk.Label(
            bc,
            text="",
            bg=CARD,
            fg=GREEN,
            font=("Segoe UI", 9, "bold"),
            justify=tk.LEFT,
        )
        self._browser_action_lbl.pack(anchor=tk.W, pady=(0, 6))

        separator(bc, pady=4)

        flat_btn(
            bc,
            "↩️  Убрать DoH политику из Chrome",
            self._action_reset_chrome_doh,
            bg=BORDER,
            fg=TEXT,
            padx=10,
        ).pack(anchor=tk.W, pady=(4, 0))

        self._net_section(p, "🎮  Активный DNS-профиль")

        main_card = tk.Frame(p, bg=CARD)
        main_card.pack(fill=tk.X, padx=14, pady=(0, 6))
        mc = tk.Frame(main_card, bg=CARD)
        mc.pack(fill=tk.X, padx=14, pady=14)

        info_frame = tk.Frame(mc, bg="#0e1f0e")
        info_frame.pack(fill=tk.X, pady=(0, 12))
        self._profile_title_lbl = tk.Label(
            info_frame,
            text="",
            bg="#0e1f0e",
            fg=GREEN,
            font=("Segoe UI", 9, "bold"),
        )
        self._profile_title_lbl.pack(anchor=tk.W, padx=10, pady=(8, 2))
        self._profile_info_lbl = tk.Label(
            info_frame,
            text="",
            bg="#0e1f0e",
            fg="#90ee90",
            font=("Segoe UI", 8),
            justify=tk.LEFT,
        )
        self._profile_info_lbl.pack(anchor=tk.W, padx=10, pady=(0, 8))

        self._btn_apply_profile = flat_btn(
            mc,
            "",
            self._action_set_xbox_dns,
            bg=XBOX_COLOR,
            padx=14,
        )
        self._btn_apply_profile.pack(fill=tk.X, pady=(0, 4))
        self._profile_apply_info_lbl = tk.Label(
            mc,
            text="",
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 8),
            justify=tk.LEFT,
        )
        self._profile_apply_info_lbl.pack(anchor=tk.W, pady=(0, 12))

        separator(mc, pady=4)

        flat_btn(
            mc,
            "🔧  Альтернатива: DNS → 127.0.0.1 (NetDocker режим)",
            self._action_set_dns,
            bg=BORDER,
            fg=TEXT,
            padx=14,
        ).pack(fill=tk.X, pady=(6, 4))
        tk.Label(
            mc,
            text=(
                "NetDocker сам будет резолвить через xbox-dns.ru DoH.\n"
                "Требует запущенного DNS-сервера NetDocker (кнопка ▶ в шапке)."
            ),
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 8),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 8))

        separator(mc, pady=4)

        flat_btn(
            mc,
            "↩️  Сбросить DNS на автоматический (DHCP)",
            self._action_reset_dns,
            bg=RED,
            fg=WHITE,
            padx=14,
        ).pack(fill=tk.X, pady=(6, 0))
        tk.Label(
            mc,
            text="Возвращает DNS на роутер (МТС снова будет перехватывать запросы).",
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(2, 10))

        separator(mc, pady=4)

        flat_btn(mc, "🗑  Очистить системный DNS-кэш (Windows)",
                 self._flush_win_cache, bg=ACCENT, padx=14).pack(fill=tk.X, pady=(6, 4))
        tk.Label(
            mc,
            text=(
                "После смены DNS при необходимости очисти кэш браузера вручную,\n"
                "если он продолжает использовать старые IP-адреса."
            ),
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 8),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(6, 0))

        self._net_action_lbl = tk.Label(p, text="", bg=BG, fg=GREEN, font=("Segoe UI", 9, "bold"))
        self._net_action_lbl.pack(anchor=tk.W, padx=14, pady=(0, 6))

        self._refresh_profile_views()
        self.after(300, self._refresh_dns_status)

    def _net_section(self, parent, title):
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill=tk.X, padx=14, pady=(14, 4))
        tk.Label(frame, text=title, bg=BG, fg=WHITE, font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)

    def _refresh_profile_views(self):
        profile = get_active_dns_profile(self.engine.config)
        if hasattr(self, "dns_panel"):
            self.dns_panel.refresh_profile(profile)
        if hasattr(self, "_browser_doh_lbl"):
            self._browser_doh_lbl.config(text=f"DoH адрес: {profile.get('doh_url') or 'не задан'}")
        if hasattr(self, "_browser_info_lbl"):
            self._browser_info_lbl.config(
                text=(
                    f"Активный профиль: {profile.get('name')}\n"
                    "Записывает DoH в браузер через политику Windows. Перезапусти браузер после изменения."
                )
            )
        if hasattr(self, "_profile_title_lbl"):
            self._profile_title_lbl.config(text=f"💡  Активный профиль: {profile.get('name')}")
        if hasattr(self, "_profile_info_lbl"):
            self._profile_info_lbl.config(
                text=(
                    f"IPv4: {profile.get('ipv4_primary') or '—'} / {profile.get('ipv4_secondary') or '—'}\n"
                    f"IPv6: {profile.get('ipv6_primary') or '—'} / {profile.get('ipv6_secondary') or '—'}\n"
                    f"DoH: {profile.get('doh_url') or 'не задан'}"
                )
            )
        if hasattr(self, "_btn_apply_profile"):
            self._btn_apply_profile.config(
                text=f"✅  Установить профиль «{profile.get('name')}» как системный DNS"
            )
        if hasattr(self, "_profile_apply_info_lbl"):
            self._profile_apply_info_lbl.config(
                text=(
                    f"Основной IPv4: {profile.get('ipv4_primary') or '—'}   Резервный IPv4: {profile.get('ipv4_secondary') or '—'}\n"
                    f"Основной IPv6: {profile.get('ipv6_primary') or '—'}   Резервный IPv6: {profile.get('ipv6_secondary') or '—'}"
                )
            )
        if hasattr(self, "profiles_tab"):
            self.profiles_tab.refresh()

    def _build_diag_table(self):
        headers = ["Источник", "Статус", "Задержка", "Комментарий"]
        header_widths = [22, 10, 12, 42]
        for col, (title, width) in enumerate(zip(headers, header_widths)):
            tk.Label(
                self._diag_table_card,
                text=title,
                width=width,
                bg=INPUT_BG,
                fg=WHITE,
                font=("Segoe UI", 8, "bold"),
                anchor=tk.W,
            ).grid(row=0, column=col, sticky="w", padx=8, pady=(8, 4))

        self._diag_table_card.grid_columnconfigure(0, weight=0, minsize=190)
        self._diag_table_card.grid_columnconfigure(1, weight=0, minsize=90)
        self._diag_table_card.grid_columnconfigure(2, weight=0, minsize=100)
        self._diag_table_card.grid_columnconfigure(3, weight=1, minsize=320)

        sources = [
            "Local DNS UDP IPv4",
            "Local DNS TCP IPv4",
            "Local DNS UDP IPv6",
            "Local DNS TCP IPv6",
            "Профиль UDP IPv4",
            "Профиль UDP IPv6",
            "Профиль DoH",
            "Fallback DNS IPv4",
            "Fallback DNS IPv6",
        ]

        for row_index, source in enumerate(sources, start=1):
            name_lbl = tk.Label(
                self._diag_table_card,
                text=source,
                width=22,
                bg=INPUT_BG,
                fg=TEXT,
                font=("Consolas", 8),
                anchor=tk.W,
            )
            name_lbl.grid(row=row_index, column=0, sticky="w", padx=8, pady=2)
            status_lbl = tk.Label(
                self._diag_table_card,
                text="—",
                width=10,
                bg=INPUT_BG,
                fg=SUBTEXT,
                font=("Segoe UI", 8, "bold"),
                anchor=tk.W,
            )
            status_lbl.grid(row=row_index, column=1, sticky="w", padx=8, pady=2)
            ms_lbl = tk.Label(
                self._diag_table_card,
                text="—",
                width=12,
                bg=INPUT_BG,
                fg=SUBTEXT,
                font=("Consolas", 8),
                anchor=tk.W,
            )
            ms_lbl.grid(row=row_index, column=2, sticky="w", padx=8, pady=2)
            comment_lbl = tk.Label(
                self._diag_table_card,
                text="",
                width=42,
                bg=INPUT_BG,
                fg=SUBTEXT,
                font=("Segoe UI", 8),
                anchor=tk.W,
                justify=tk.LEFT,
            )
            comment_lbl.grid(row=row_index, column=3, sticky="ew", padx=8, pady=2)
            self._diag_rows[source] = (status_lbl, ms_lbl, comment_lbl)

    def _set_diag_row(self, source, status, latency=None, comment=""):
        if source not in self._diag_rows:
            return
        status_lbl, ms_lbl, comment_lbl = self._diag_rows[source]
        color_map = {"OK": GREEN, "WARN": YELLOW, "FAIL": RED, "INFO": SUBTEXT}
        status_lbl.config(text=status, fg=color_map.get(status, SUBTEXT))
        ms_lbl.config(text=(f"{latency} мс" if isinstance(latency, int) else "—"),
                      fg=("#4ecca3" if isinstance(latency, int) else SUBTEXT))
        compact_comment = str(comment).replace("\n", " ").strip()
        if len(compact_comment) > 58:
            compact_comment = compact_comment[:55] + "..."
        comment_lbl.config(text=compact_comment, fg=SUBTEXT)

    def _set_diag_pending(self):
        for source in self._diag_rows:
            self._set_diag_row(source, "INFO", None, "Проверка...")

    def _copy_diag_report(self):
        report = getattr(self, "_last_diag_report", "Диагностика ещё не запускалась")
        copy_to_clipboard(self, report)
        self._net_action_lbl.config(text="✅ Отчёт диагностики скопирован", fg=GREEN)

    def _check_dns_leak(self, _retry=False):
        """Проверка утечки DNS (в основном IPv6) + предложение исправить.

        Индикатор «Ищу…/Готово» показываем прямо на кнопке, т.к. строка статуса
        находится далеко внизу и пользователю не видна.
        """
        # сразу даём визуальный отклик на самой кнопке
        self._leak_btn.config(text="⏳ Ищу…", state=tk.DISABLED)
        self._net_action_lbl.config(text="⏳ Проверяю утечку DNS…", fg=YELLOW)
        self.update_idletasks()  # форсим перерисовку до запуска потока

        def run():
            res = self.engine.check_dns_leak()

            def show():
                self._leak_btn.config(text="🛡 Проверить утечку DNS", state=tk.NORMAL)
                status = res.get("status")
                title = res.get("title", "")
                details = res.get("details", [])

                # Если это ПОВТОРНАЯ проверка после исправления — только сообщаем
                # результат, БЕЗ повторного диалога «Да/Нет» (иначе бесконечный цикл).
                if _retry:
                    if status == "ok":
                        self._net_action_lbl.config(text="✅ Утечка устранена", fg=GREEN)
                        messagebox.showinfo("Готово", "Утечка DNS устранена ✅")
                    else:
                        self._net_action_lbl.config(
                            text="⚠ Утечка осталась — нужно отключить IPv6 вручную", fg=RED)
                        messagebox.showwarning(
                            "Утечка осталась",
                            title + "\n\n" + "\n".join(f"• {d}" for d in details) +
                            "\n\nАвтоматическое исправление не помогло. Самый "
                            "надёжный способ — вручную отключить протокол IPv6 в "
                            "свойствах сетевого адаптера (ncpa.cpl).")
                    return

                if status == "ok":
                    self._net_action_lbl.config(text="✅ Готово: " + title, fg=GREEN)
                    messagebox.showinfo("Проверка утечки DNS", title)
                elif status == "unknown":
                    self._net_action_lbl.config(text=title, fg=SUBTEXT)
                    messagebox.showinfo("Проверка утечки DNS", title)
                else:  # risk
                    self._net_action_lbl.config(text=title, fg=YELLOW)
                    msg = title + "\n\n" + "\n".join(f"• {d}" for d in details)
                    if res.get("can_fix") and is_admin():
                        msg += ("\n\nКак исправить?\n"
                                "«Да» — пустить IPv6 через обход (включит наш "
                                "IPv6-сервер и направит на ::1)\n"
                                "«Нет» — отключить IPv6 на адаптерах (надёжно "
                                "убирает утечку, если IPv6 вам не нужен)")
                        ans = messagebox.askyesnocancel("⚠ Возможна утечка DNS", msg)
                        if ans is None:
                            return
                        self._leak_btn.config(text="⏳ Исправляю…", state=tk.DISABLED)
                        self.update_idletasks()
                        ok, fmsg = self.engine.fix_dns_leak(disable_ipv6=(ans is False))
                        self._leak_btn.config(text="🛡 Проверить утечку DNS", state=tk.NORMAL)
                        if ok:
                            try:
                                from process_monitor import flush_dns_cache
                                flush_dns_cache()
                            except Exception:
                                pass
                            self._net_action_lbl.config(text="✅ " + fmsg + " — перепроверяю…", fg=GREEN)
                            # ОДНА повторная проверка в режиме _retry (без диалога)
                            self.after(600, lambda: self._check_dns_leak(_retry=True))
                        else:
                            self._net_action_lbl.config(text="⚠ " + fmsg, fg=RED)
                            messagebox.showwarning("Не удалось исправить", fmsg)
                    else:
                        if not is_admin():
                            msg += ("\n\nДля исправления запустите NetDocker "
                                    "от администратора и включите DNS-сервер.")
                        messagebox.showwarning("⚠ Возможна утечка DNS", msg)

            self.after(0, show)

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _probe_tcp(host, port, family=socket.AF_INET, timeout=2.5):
        import time
        try:
            t0 = time.perf_counter()
            address = (host, port, 0, 0) if family == socket.AF_INET6 else (host, port)
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(address)
            sock.close()
            return True, int((time.perf_counter() - t0) * 1000), "порт доступен"
        except Exception as exc:
            return False, None, str(exc)

    @staticmethod
    def _probe_udp_dns(host, qname="google.com", qtype="A", timeout=3.0):
        import time
        from dnslib import DNSRecord
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        address = (host, 53, 0, 0) if family == socket.AF_INET6 else (host, 53)
        try:
            req = DNSRecord.question(qname, qtype)
            sock = socket.socket(family, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            t0 = time.perf_counter()
            sock.sendto(req.pack(), address)
            data, _ = sock.recvfrom(65535)
            sock.close()
            resp = DNSRecord.parse(data)
            answers = len(resp.rr)
            return True, int((time.perf_counter() - t0) * 1000), f"ответов: {answers}"
        except Exception as exc:
            return False, None, str(exc)

    @staticmethod
    def _probe_doh(url, timeout=4.0):
        import base64
        import time
        from dnslib import DNSRecord as DR
        try:
            req = DR.question("google.com", "A")
            b64 = base64.urlsafe_b64encode(req.pack()).rstrip(b'=').decode()
            t0 = time.perf_counter()
            resp = requests.get(url,
                                headers={"Accept": "application/dns-message"},
                                params={"dns": b64}, timeout=timeout)
            resp.raise_for_status()
            DR.parse(resp.content)
            return True, int((time.perf_counter() - t0) * 1000), "DoH доступен"
        except Exception as exc:
            return False, None, str(exc)

    def _on_tab_changed(self, _event):
        try:
            current = self.nb.nametowidget(self.nb.select())
        except Exception:
            return
        if current == getattr(self, "tab_net", None):
            self._refresh_dns_status()
        elif current == getattr(self, "tab_profiles", None) and hasattr(self, "profiles_tab"):
            self.profiles_tab.refresh()

    def _refresh_dns_status(self):
        if self._diag_refreshing:
            return
        self._diag_refreshing = True
        self._set_diag_pending()

        def run():
            try:
                report_lines = []
                profile = get_active_dns_profile(self.engine.config)

                checks = [
                    ("Local DNS UDP IPv4", lambda: self._probe_udp_dns("127.0.0.1", qtype="A")),
                    ("Local DNS TCP IPv4", lambda: self._probe_tcp("127.0.0.1", self.engine.config.get("listen_port", 53), socket.AF_INET)),
                    ("Local DNS UDP IPv6", lambda: self._probe_udp_dns("::1", qtype="AAAA")),
                    ("Local DNS TCP IPv6", lambda: self._probe_tcp("::1", self.engine.config.get("listen_port", 53), socket.AF_INET6)),
                    ("Профиль UDP IPv4", lambda: self._probe_udp_dns(profile.get("ipv4_primary"), qtype="A")) if profile.get("ipv4_primary") else None,
                    ("Профиль UDP IPv6", lambda: self._probe_udp_dns(profile.get("ipv6_primary"), qtype="AAAA")) if profile.get("ipv6_primary") else None,
                    ("Профиль DoH", lambda: self._probe_doh(profile.get("doh_url"))) if profile.get("doh_url") else None,
                    ("Fallback DNS IPv4", lambda: self._probe_udp_dns(self.engine.config.get("fallback_dns"), qtype="A")) if self.engine.config.get("fallback_dns") else None,
                    ("Fallback DNS IPv6", lambda: self._probe_udp_dns(self.engine.config.get("fallback_dns6"), qtype="AAAA")) if self.engine.config.get("fallback_dns6") else None,
                ]

                row_updates = []
                for entry in checks:
                    if entry is None:
                        continue
                    source, fn = entry
                    try:
                        ok, latency, comment = fn()
                    except Exception as exc:
                        ok, latency, comment = False, None, str(exc)
                    status = "OK" if ok else "FAIL"
                    row_updates.append((source, status, latency, comment))
                    report_lines.append(f"{source}: {status} | {latency if latency is not None else '-'} | {comment}")

                if not profile.get("ipv4_primary"):
                    row_updates.append(("Профиль UDP IPv4", "INFO", None, "не задан"))
                if not profile.get("ipv6_primary"):
                    row_updates.append(("Профиль UDP IPv6", "INFO", None, "не задан"))
                if not profile.get("doh_url"):
                    row_updates.append(("Профиль DoH", "INFO", None, "не задан"))
                if not self.engine.config.get("fallback_dns6"):
                    row_updates.append(("Fallback DNS IPv6", "INFO", None, "не задан"))
                if not self.engine.config.get("enable_ipv6", True):
                    row_updates.append(("Local DNS UDP IPv6", "WARN", None, "IPv6 отключён в настройках"))
                    row_updates.append(("Local DNS TCP IPv6", "WARN", None, "IPv6 отключён в настройках"))

                report = "Диагностика апстримов:\n" + "\n".join(report_lines)

                def apply_ui():
                    for source, status, latency, comment in row_updates:
                        self._set_diag_row(source, status, latency, comment)
                    self._last_diag_report = report
                    self._diag_refreshing = False

                self.after(0, apply_ui)
            except Exception as exc:
                # Захватываем текст в локальную переменную: имя из
                # `except ... as exc` удаляется при выходе из блока except,
                # а apply_error() вызывается позже (через after) — иначе NameError.
                err_text = str(exc)
                def apply_error():
                    for source in self._diag_rows:
                        self._set_diag_row(source, "FAIL", None, f"Ошибка диагностики: {err_text}")
                    self._last_diag_report = f"Ошибка диагностики: {err_text}"
                    self._diag_refreshing = False
                self.after(0, apply_error)

    def _action_set_xbox_dns(self):
        if not is_admin():
            messagebox.showerror(
                "Нет прав",
                "Требуются права администратора.\nЗапусти start.bat правой кнопкой → «От имени администратора»."
            )
            return
        profile = get_active_dns_profile(self.engine.config)
        self._net_action_lbl.config(text=f"⏳ Устанавливаю профиль «{profile.get('name')}»...", fg=YELLOW)
        self.update()

        def run():
            ok, msg, adapters = set_dns_profile(
                profile.get("ipv4_primary", ""),
                profile.get("ipv4_secondary", ""),
                profile.get("ipv6_primary", ""),
                profile.get("ipv6_secondary", ""),
                profile_name=profile.get("name", "DNS-профиль"),
            )
            if ok:
                text = f"✅ Профиль «{profile.get('name')}» установлен на: {', '.join(adapters)}"
                color = GREEN
                self.after(500, self._refresh_dns_status)
            else:
                text = f"❌ {msg}"
                color = RED
            self.after(0, lambda: self._net_action_lbl.config(text=text, fg=color))

        threading.Thread(target=run, daemon=True).start()

    def _action_set_dns(self):
        if not is_admin():
            messagebox.showerror(
                "Нет прав",
                "Программа запущена без прав администратора!\n\n"
                "Закрой программу и запусти start.bat\n"
                "правой кнопкой → «Запустить от имени администратора»."
            )
            return

        self._net_action_lbl.config(text="⏳ Устанавливаю DNS...", fg=YELLOW)
        self.update()

        def run():
            cfg = self.engine.config
            ok, msg, adapters = set_dns_to_localhost(
                fallback_ipv4=cfg.get("fallback_dns", "1.1.1.1"),
                fallback_ipv6=cfg.get("fallback_dns6", ""),
                enable_ipv6=cfg.get("enable_ipv6", True),
            )
            if ok:
                text = f"✅ DNS установлен на: {', '.join(adapters)}"
                color = GREEN
                self.after(500, self._refresh_dns_status)
            else:
                text = f"❌ Ошибка: {msg}"
                color = RED
            self.after(0, lambda: self._net_action_lbl.config(text=text, fg=color))

        threading.Thread(target=run, daemon=True).start()

    def _action_reset_dns(self):
        if not is_admin():
            messagebox.showerror("Нет прав", "Требуются права администратора.")
            return

        self._net_action_lbl.config(text="⏳ Сбрасываю DNS...", fg=YELLOW)
        self.update()

        def run():
            ok, msg = reset_dns_to_auto()
            self.after(0, lambda: self._net_action_lbl.config(text=(f"✅ {msg}" if ok else f"❌ {msg}"), fg=(GREEN if ok else RED)))
            if ok:
                self.after(500, self._refresh_dns_status)

        threading.Thread(target=run, daemon=True).start()

    def _action_set_chrome_doh(self):
        profile = get_active_dns_profile(self.engine.config)
        doh_url = profile.get("doh_url")
        if not doh_url:
            self._browser_action_lbl.config(text="❌ У активного профиля не задан DoH URL", fg=RED)
            return
        self._browser_action_lbl.config(text="⏳ Прописываю DoH в Chrome...", fg=YELLOW)
        self.update()

        def run():
            ok, msg = set_chrome_doh(doh_url)
            text = f"✅ {msg}" if ok else f"❌ {msg}"
            color = GREEN if ok else RED
            self.after(0, lambda: self._browser_action_lbl.config(text=text, fg=color))
            if ok:
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Chrome DoH установлен",
                        f"DoH прописан в Chrome:\n{doh_url}\n\n"
                        f"Активный профиль: {profile.get('name')}\n\n"
                        "Перезапусти Chrome для применения.",
                    ),
                )

        threading.Thread(target=run, daemon=True).start()

    def _action_set_edge_doh(self):
        profile = get_active_dns_profile(self.engine.config)
        doh_url = profile.get("doh_url")
        if not doh_url:
            self._browser_action_lbl.config(text="❌ У активного профиля не задан DoH URL", fg=RED)
            return
        self._browser_action_lbl.config(text="⏳ Прописываю DoH в Edge...", fg=YELLOW)
        self.update()

        def run():
            ok, msg = set_edge_doh(doh_url)
            text = f"✅ {msg}" if ok else f"❌ {msg}"
            color = GREEN if ok else RED
            self.after(0, lambda: self._browser_action_lbl.config(text=text, fg=color))
            if ok:
                self.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Edge DoH установлен",
                        f"DoH прописан в Edge:\n{doh_url}\n\nПерезапусти Edge для применения.",
                    ),
                )

        threading.Thread(target=run, daemon=True).start()

    def _action_reset_chrome_doh(self):
        self._browser_action_lbl.config(text="⏳ Удаляю DoH политику Chrome...", fg=YELLOW)
        self.update()

        def run():
            ok, msg = reset_chrome_doh()
            self.after(0, lambda: self._browser_action_lbl.config(text=(f"✅ {msg}" if ok else f"❌ {msg}"), fg=(GREEN if ok else RED)))

        threading.Thread(target=run, daemon=True).start()

    def _flush_win_cache(self):
        def run():
            ok = flush_dns_cache()
            msg = "✅ DNS-кэш Windows очищен" if ok else "❌ Не удалось очистить кэш"
            self.after(0, lambda: self._net_action_lbl.config(text=msg, fg=(GREEN if ok else RED)))

        threading.Thread(target=run, daemon=True).start()
        self._net_action_lbl.config(text="⏳ Очищаю кэш...", fg=YELLOW)

    def _open_chrome_cache(self):
        self._open_url("chrome://net-internals/#dns")

    def _open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc))

    def _on_close(self):
        """Крестик окна → сворачиваем в трей (не выходим).
        Программа продолжает работать в фоне — «поставил и забыл».
        Полный выход — через меню трея «Выход» (_quit_app).
        """
        self.withdraw()
        # Один раз подсказываем, что прога ушла в трей, а не закрылась.
        if not getattr(self, "_tray_hint_shown", False):
            self._tray_hint_shown = True
            try:
                if hasattr(self, "tray") and self.tray:
                    self.tray.notify(
                        "NetDocker свёрнут в трей и продолжает работать.\n"
                        "Полный выход — правый клик по иконке → «Выход»."
                    )
            except Exception:
                pass

    def _quit_app(self):
        """Полный выход из программы (из меню трея «Выход»).
        Если DNS-сервер запущен — корректно останавливаем и возвращаем DNS на авто.
        """
        try:
            if self.engine and self.engine.running:
                # _stop в ControlBar сам останавливает сервер и сбрасывает DNS
                if hasattr(self, "ctrl") and self.ctrl:
                    self.ctrl._stop()
                else:
                    self.engine.stop()
        except Exception:
            pass
        if hasattr(self, "tray") and self.tray:
            self.tray.stop()
        self.destroy()

    def _warn_admin(self):
        messagebox.showwarning(
            "Без прав администратора",
            "Программа запущена без прав администратора.\n\n"
            "Запустите её через start.bat — он автоматически\n"
            "запросит права (окно UAC). Без прав не получится\n"
            "занять порт 53 и переключить системный DNS.",
        )



def main():
    # Защита от запуска второй копии.
    from single_instance import SingleInstance, request_show_existing
    guard = SingleInstance()
    if guard.already_running():
        # Просим уже работающую копию показать своё окно — и выходим без второй иконкой.
        request_show_existing()
        return

    app = NetDockerApp()
    try:
        app.mainloop()
    finally:
        guard.release()


if __name__ == "__main__":
    main()
