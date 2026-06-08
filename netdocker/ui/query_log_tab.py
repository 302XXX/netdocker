"""
Вкладка «📊 Журнал» — живой Query Log DNS-запросов.

Подписывается на глобальный QueryLog (см. query_log.py), показывает
новые записи в Treeview, поддерживает поиск/фильтр/пауза/очистка/экспорт.

Архитектура:
  - QueryLog работает в DNS-потоке, callback приходит оттуда.
  - GUI принимает события через очередь и обновляет Treeview
    в Tk-потоке через self.after() — иначе Tkinter падает.
"""

import csv
import os
import queue
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from query_log import (
    SOURCE_BOGUS_NX,
    SOURCE_CACHE_FRESH,
    SOURCE_CACHE_STALE,
    SOURCE_ROUTED,
    SOURCE_SERVFAIL,
    SOURCE_SYSTEM,
    get_query_log,
)
from ui.common import (
    ACCENT, BG, BORDER, CARD, GREEN, INPUT_BG,
    RED, SUBTEXT, TEXT, WHITE, YELLOW, flat_btn,
)


# ── Стилизация источников ───────────────────────────────────────────────────
# Каждый source отрисовывается с эмодзи-префиксом и цветом строки в Treeview.
SOURCE_STYLE = {
    SOURCE_CACHE_FRESH:  ("💾 кэш",          "#4ecca3"),
    SOURCE_CACHE_STALE:  ("⚡ кэш (stale)",  "#facc15"),
    SOURCE_ROUTED:       ("🚀 маршрут",      ACCENT),
    SOURCE_SYSTEM:       ("🌐 система",      TEXT),
    SOURCE_BOGUS_NX:     ("🛡 подмена→NX",   RED),
    SOURCE_SERVFAIL:     ("❌ SERVFAIL",     RED),
}

FILTER_ALL = "Все"
FILTER_ROUTED = "🚀 Маршрут"
FILTER_CACHE = "💾 Кэш"
FILTER_BOGUS = "🛡 Подмена"
FILTER_ERRORS = "❌ Ошибки"

FILTERS = [FILTER_ALL, FILTER_ROUTED, FILTER_CACHE, FILTER_BOGUS, FILTER_ERRORS]


def _entry_matches_filter(entry, filter_name: str) -> bool:
    if filter_name == FILTER_ALL:
        return True
    if filter_name == FILTER_ROUTED:
        return bool(entry.routed) or entry.source == SOURCE_ROUTED
    if filter_name == FILTER_CACHE:
        return entry.source in (SOURCE_CACHE_FRESH, SOURCE_CACHE_STALE)
    if filter_name == FILTER_BOGUS:
        return entry.source == SOURCE_BOGUS_NX
    if filter_name == FILTER_ERRORS:
        return entry.source == SOURCE_SERVFAIL or entry.rcode not in ("NOERROR", "")
    return True


def _entry_matches_search(entry, needle_lower: str) -> bool:
    if not needle_lower:
        return True
    if needle_lower in entry.domain.lower():
        return True
    for ans in entry.answers:
        if needle_lower in str(ans).lower():
            return True
    if needle_lower in entry.note.lower():
        return True
    return False


class QueryLogTab(tk.Frame):
    """Вкладка «📊 Журнал»."""

    # Сколько максимум строк отрисовываем в Treeview за один тик —
    # чтобы при шторме запросов GUI не лагал.
    BATCH_PER_TICK = 50
    TICK_MS = 200

    def __init__(self, parent, engine, **kw):
        super().__init__(parent, bg=BG, **kw)
        self.engine = engine
        self.query_log = get_query_log()

        # Очередь между DNS-потоком и Tk-потоком: subscriber толкает сюда,
        # _drain_queue() в Tk-потоке через after() забирает.
        self._incoming: "queue.Queue" = queue.Queue()
        self._search_var = tk.StringVar()
        self._filter_var = tk.StringVar(value=FILTER_ALL)
        self._paused = False
        # Маппинг "iid строки в Treeview → entry" — нужно для экспорта
        # и для перерисовки при смене поиска/фильтра.
        self._row_to_entry = {}

        self._build()
        self._populate_initial()
        self._subscribe()
        self.after(self.TICK_MS, self._drain_queue)
        # При уничтожении вкладки — отписаться, иначе будет утечка.
        self.bind("<Destroy>", lambda _e: self._unsubscribe())

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build(self):
        toolbar = tk.Frame(self, bg=BG)
        toolbar.pack(fill=tk.X, padx=12, pady=(10, 6))

        # Поиск
        tk.Label(toolbar, text="🔍", bg=BG, fg=SUBTEXT,
                 font=("Segoe UI Emoji", 11)).pack(side=tk.LEFT, padx=(0, 4))
        search_entry = tk.Entry(
            toolbar, textvariable=self._search_var,
            bg=INPUT_BG, fg=TEXT, insertbackground=WHITE,
            relief=tk.FLAT, font=("Consolas", 9), width=28,
        )
        search_entry.pack(side=tk.LEFT, ipady=4)
        self._search_var.trace_add("write", lambda *_a: self._refilter())

        # Фильтр — свой dropdown в стиле приложения (без белого ttk.Combobox).
        # ttk.Combobox в темной теме выглядит как кусок Windows 95, поэтому
        # делаем кнопку с тёмным фоном и тонкой рамкой, по клику — Menu.
        tk.Label(toolbar, text="  Фильтр:", bg=BG, fg=SUBTEXT,
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(12, 4))
        filter_wrap = tk.Frame(
            toolbar, bg=INPUT_BG,
            highlightbackground=BORDER, highlightthickness=1,
        )
        filter_wrap.pack(side=tk.LEFT)
        self._filter_btn = tk.Button(
            filter_wrap,
            text=f"{FILTER_ALL}  ▾",
            command=self._show_filter_menu,
            bg=INPUT_BG, fg=TEXT,
            activebackground=INPUT_BG, activeforeground=WHITE,
            relief=tk.FLAT, bd=0, cursor="hand2",
            anchor=tk.W, font=("Segoe UI", 9),
            padx=10, pady=4, width=14,
        )
        self._filter_btn.pack()
        style = ttk.Style()
        try:
            style.theme_use(style.theme_use())
        except Exception:
            pass

        # Кнопки справа
        self._btn_export = flat_btn(
            toolbar, "💾 Экспорт", self._export, bg=BORDER, fg=TEXT, padx=10,
        )
        self._btn_export.pack(side=tk.RIGHT, padx=(6, 0))

        self._btn_clear = flat_btn(
            toolbar, "🗑 Очистить", self._clear, bg=RED, padx=10,
        )
        self._btn_clear.pack(side=tk.RIGHT, padx=(6, 0))

        self._btn_pause = flat_btn(
            toolbar, "⏸ Пауза", self._toggle_pause, bg=YELLOW, fg="#1a1a2e", padx=10,
        )
        self._btn_pause.pack(side=tk.RIGHT, padx=(6, 0))

        # ── Treeview ────────────────────────────────────────────────────────
        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(4, 8))

        # Стиль для тёмной темы. ttk крайне неохотно красится — приходится
        # явно прописывать всё.
        style.configure(
            "QueryLog.Treeview",
            background=INPUT_BG,
            foreground=TEXT,
            fieldbackground=INPUT_BG,
            borderwidth=0,
            rowheight=22,
            font=("Consolas", 9),
        )
        style.configure(
            "QueryLog.Treeview.Heading",
            background=CARD,
            foreground=WHITE,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        # Гасим белый hover/active у заголовков — они НЕ кнопки,
        # незачем им «нажиматься» под курсором.
        style.map(
            "QueryLog.Treeview.Heading",
            background=[("active", CARD), ("pressed", CARD)],
            foreground=[("active", WHITE), ("pressed", WHITE)],
            relief=[("active", "flat"), ("pressed", "flat")],
        )
        # Подсветка ВЫБРАННОЙ строки — наш акцентный синий.
        # На hover ничего не делаем (active даёт hover-эффект на старых темах
        # типа "default" — отключаем).
        style.map(
            "QueryLog.Treeview",
            background=[("selected", ACCENT), ("active", INPUT_BG)],
            foreground=[("selected", WHITE), ("active", TEXT)],
        )

        columns = ("time", "domain", "qtype", "source", "latency")
        self.tree = ttk.Treeview(
            body, columns=columns, show="headings",
            style="QueryLog.Treeview", height=22,
        )
        self.tree.heading("time", text="Время")
        self.tree.heading("domain", text="Домен")
        self.tree.heading("qtype", text="Тип")
        self.tree.heading("source", text="Источник")
        self.tree.heading("latency", text="мс")

        self.tree.column("time", width=80, anchor=tk.W, stretch=False)
        self.tree.column("domain", width=320, anchor=tk.W)
        self.tree.column("qtype", width=60, anchor=tk.W, stretch=False)
        self.tree.column("source", width=130, anchor=tk.W, stretch=False)
        self.tree.column("latency", width=70, anchor=tk.E, stretch=False)

        vsb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Цветовые теги для строк (по source) — добавляются ниже.
        for source, (_label, color) in SOURCE_STYLE.items():
            self.tree.tag_configure(source, foreground=color)

        # Двойной клик по строке — показать детали в маленьком окне.
        self.tree.bind("<Double-1>", self._show_details)

        # Статус-бар внизу.
        self._status_var = tk.StringVar(value="Журнал пуст")
        tk.Label(
            self, textvariable=self._status_var, bg=BG, fg=SUBTEXT,
            font=("Segoe UI", 8), anchor=tk.W,
        ).pack(fill=tk.X, padx=12, pady=(0, 6))

    # ── Подписка и приём событий ────────────────────────────────────────────
    def _subscribe(self):
        self._on_new_entry_ref = self._on_new_entry  # держим ссылку, чтобы unsubscribe нашёл
        self.query_log.subscribe(self._on_new_entry_ref)

    def _unsubscribe(self):
        if hasattr(self, "_on_new_entry_ref"):
            self.query_log.unsubscribe(self._on_new_entry_ref)

    def _on_new_entry(self, entry):
        """Этот callback вызывается из DNS-потока. Просто кладём в очередь."""
        try:
            self._incoming.put_nowait(entry)
        except Exception:
            pass

    def _drain_queue(self):
        """Tk-таймер: разгружаем очередь, добавляя в Treeview пакетами."""
        try:
            inserted = 0
            while inserted < self.BATCH_PER_TICK:
                try:
                    entry = self._incoming.get_nowait()
                except queue.Empty:
                    break
                if _entry_matches_filter(entry, self._filter_var.get()) and \
                        _entry_matches_search(entry, self._search_var.get().strip().lower()):
                    self._insert_entry(entry)
                inserted += 1
            if inserted > 0:
                self._trim_to_max()
                self._update_status()
        finally:
            # Перезапускаем себя — даже если вкладку убили, after-таймер
            # просто не найдёт виджет и тихо отвалится.
            try:
                self.after(self.TICK_MS, self._drain_queue)
            except Exception:
                pass

    # ── Отрисовка ───────────────────────────────────────────────────────────
    def _populate_initial(self):
        """Загружает уже накопленные записи (если вкладка открыта не сразу)."""
        for entry in self.query_log.snapshot():
            if _entry_matches_filter(entry, self._filter_var.get()) and \
                    _entry_matches_search(entry, self._search_var.get().strip().lower()):
                self._insert_entry(entry)
        self._update_status()

    def _insert_entry(self, entry):
        time_str = time.strftime("%H:%M:%S", time.localtime(entry.timestamp))
        label, _color = SOURCE_STYLE.get(entry.source, (entry.source, TEXT))
        latency_text = "—" if entry.source in (SOURCE_CACHE_FRESH, SOURCE_CACHE_STALE) \
            and entry.latency_ms == 0 else f"{entry.latency_ms}"
        # Routed-домен помечаем в колонке домена жирным префиксом — это
        # быстрая визуальная подсказка, что прога именно его маршрутизирует.
        domain_text = ("• " + entry.domain) if entry.routed else entry.domain
        iid = self.tree.insert(
            "", tk.END,
            values=(time_str, domain_text, entry.qtype, label, latency_text),
            tags=(entry.source,),
        )
        self._row_to_entry[iid] = entry
        # Автопрокрутка только если пользователь уже смотрит в конец.
        # Иначе раздражает, когда читаешь старую запись и тебя дёргает вниз.
        try:
            yview = self.tree.yview()
            if yview and yview[1] > 0.95:
                self.tree.see(iid)
        except Exception:
            pass

    def _trim_to_max(self):
        """Не даём Treeview расти бесконечно — синхронизируем с размером буфера."""
        max_rows = len(self.query_log)  # столько же, сколько в буфере (или меньше)
        children = self.tree.get_children()
        excess = len(children) - max_rows
        if excess > 0:
            for iid in children[:excess]:
                self._row_to_entry.pop(iid, None)
                try:
                    self.tree.delete(iid)
                except Exception:
                    pass

    def _refilter(self):
        """Полная перерисовка под текущий фильтр+поиск."""
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_to_entry.clear()
        self._populate_initial()

    def _show_filter_menu(self):
        """Свой dropdown для фильтра в тёмной теме (вместо ttk.Combobox)."""
        menu = tk.Menu(
            self, tearoff=0,
            bg=CARD, fg=TEXT,
            activebackground=ACCENT, activeforeground=WHITE,
            font=("Segoe UI", 9), bd=0,
        )
        current = self._filter_var.get()
        for name in FILTERS:
            prefix = "✓ " if name == current else "   "
            menu.add_command(
                label=f"{prefix}{name}",
                command=lambda n=name: self._set_filter(n),
            )
        x = self._filter_btn.winfo_rootx()
        y = self._filter_btn.winfo_rooty() + self._filter_btn.winfo_height() + 2
        menu.tk_popup(x, y)

    def _set_filter(self, name):
        self._filter_var.set(name)
        try:
            self._filter_btn.config(text=f"{name}  ▾")
        except Exception:
            pass
        self._refilter()

    # ── Кнопки ──────────────────────────────────────────────────────────────
    def _toggle_pause(self):
        self._paused = not self._paused
        self.query_log.set_paused(self._paused)
        if self._paused:
            self._btn_pause.config(text="▶ Возобновить", bg=GREEN, fg=WHITE)
            self._set_status("⏸ Журнал на паузе — новые запросы пишутся в буфер, но не показываются")
        else:
            self._btn_pause.config(text="⏸ Пауза", bg=YELLOW, fg="#1a1a2e")
            # Подхватываем пропущенное за паузу из снапшота.
            self._refilter()

    def _clear(self):
        if not messagebox.askyesno(
            "Очистить журнал",
            "Удалить все записи журнала?\n\nDNS-кэш программы это не затронет.",
            parent=self,
        ):
            return
        self.query_log.clear()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        self._row_to_entry.clear()
        self._update_status()

    def _export(self):
        entries = self.query_log.snapshot()
        if not entries:
            messagebox.showinfo("Экспорт", "Журнал пуст — нечего экспортировать.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Сохранить журнал",
            defaultextension=".csv",
            initialfile=f"netdocker-querylog-{time.strftime('%Y%m%d-%H%M%S')}.csv",
            filetypes=[("CSV (для Excel/таблиц)", "*.csv"), ("Текстовый файл", "*.txt")],
        )
        if not path:
            return
        try:
            if path.lower().endswith(".txt"):
                with open(path, "w", encoding="utf-8") as f:
                    for e in entries:
                        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
                        ans = ", ".join(e.answers) if e.answers else ""
                        routed_mark = "ROUTED" if e.routed else ""
                        f.write(
                            f"{ts}\t{e.qtype}\t{e.domain}\t{e.source}\t"
                            f"{e.rcode}\t{e.latency_ms}ms\t{routed_mark}\t{ans}\t{e.note}\n"
                        )
            else:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow([
                        "timestamp", "datetime", "domain", "qtype",
                        "source", "routed", "rcode", "latency_ms", "answers", "note",
                    ])
                    for e in entries:
                        ts_iso = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp))
                        w.writerow([
                            f"{e.timestamp:.3f}", ts_iso, e.domain, e.qtype,
                            e.source, "1" if e.routed else "0", e.rcode, e.latency_ms,
                            " | ".join(e.answers), e.note,
                        ])
        except Exception as exc:
            messagebox.showerror("Экспорт", f"Не удалось сохранить файл:\n{exc}", parent=self)
            return
        self._set_status(f"💾 Сохранено: {os.path.basename(path)} ({len(entries)} записей)")

    # ── Детали по двойному клику ────────────────────────────────────────────
    def _show_details(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        entry = self._row_to_entry.get(sel[0])
        if entry is None:
            return
        win = tk.Toplevel(self)
        win.title(f"Детали: {entry.domain}")
        win.configure(bg=BG)
        win.geometry("560x340")
        win.minsize(420, 260)

        body = tk.Frame(win, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        def row(label, value, color=TEXT):
            r = tk.Frame(body, bg=BG)
            r.pack(fill=tk.X, pady=2)
            tk.Label(r, text=label, bg=BG, fg=SUBTEXT,
                     font=("Segoe UI", 9), width=14, anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(r, text=value, bg=BG, fg=color,
                     font=("Consolas", 9), anchor=tk.W, justify=tk.LEFT).pack(side=tk.LEFT)

        row("Время:", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.timestamp)))
        row("Домен:", entry.domain)
        row("Тип:", entry.qtype)
        row("Routed:", "ДА" if entry.routed else "нет",
            color=GREEN if entry.routed else SUBTEXT)
        src_label, src_color = SOURCE_STYLE.get(entry.source, (entry.source, TEXT))
        row("Источник:", src_label, color=src_color)
        row("RCODE:", entry.rcode, color=RED if entry.rcode not in ("NOERROR", "") else TEXT)
        row("Latency:", f"{entry.latency_ms} мс")
        if entry.note:
            row("Заметка:", entry.note, color=YELLOW)
        if entry.answers:
            tk.Label(body, text="Ответы:", bg=BG, fg=SUBTEXT,
                     font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(8, 2))
            text = tk.Text(body, bg=INPUT_BG, fg=TEXT, height=8,
                           font=("Consolas", 9), relief=tk.FLAT, wrap=tk.WORD)
            text.pack(fill=tk.BOTH, expand=True)
            text.insert("1.0", "\n".join(entry.answers))
            text.config(state=tk.DISABLED)

    # ── Статус ──────────────────────────────────────────────────────────────
    def _update_status(self):
        total = len(self.query_log)
        shown = len(self.tree.get_children())
        if total == 0:
            self._set_status("Журнал пуст — запусти DNS-сервер и сделай DNS-запрос")
        elif total == shown:
            self._set_status(f"Записей: {total}")
        else:
            self._set_status(f"Показано: {shown} из {total} (фильтр/поиск активен)")

    def _set_status(self, text):
        self._status_var.set(text)
