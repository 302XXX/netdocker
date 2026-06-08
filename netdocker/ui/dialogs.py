import os
import threading
import time
import tkinter as tk
from tkinter import messagebox

from backup_utils import create_config_backup, list_config_backups, load_config_backup
from config_utils import DEFAULT_CONFIG
from dns_server import save_config
from process_monitor import get_running_processes, XBOX_DOH_URL
from routed_presets import ROUTED_PRESETS, get_routed_preset_map, get_routed_preset_name
from routing_utils import is_domain_routed
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
    YELLOW,
    PresetSlider,
    flat_btn,
)


class TestWindow(tk.Toplevel):
    """
    Полноценное окно тестирования:
      • Пинг DNS-серверов (системный + DoH + xbox-dns.ru)
      • Резолвинг любого домена через системный DNS и через DoH
      • Цветная индикация результатов
    """

    DNS_SERVERS = [
        ("Системный DNS", None, "auto"),
        ("Cloudflare", "1.1.1.1", "#f48120"),
        ("Google DNS", "8.8.8.8", "#4285f4"),
        ("Quad9", "9.9.9.9", "#6c4fa1"),
        ("xbox-dns.ru DoH", None, "#107c10"),
    ]

    QUICK_DOMAINS = [
        "chatgpt.com", "openai.com", "claude.ai",
        "google.com", "ya.ru", "github.com",
    ]

    def __init__(self, parent, engine):
        super().__init__(parent)
        self.engine = engine
        self.title("🧪 Тест DNS и доменов")
        self.configure(bg=BG)
        self.geometry("720x620")
        self.minsize(640, 520)
        self.resizable(True, True)
        self.grab_set()
        self._running = False
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=ACCENT, height=44)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text="🧪  Тест DNS и доменов",
            bg=ACCENT,
            fg=WHITE,
            font=("Segoe UI", 13, "bold"),
        ).pack(side=tk.LEFT, padx=16)

        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)

        left = tk.Frame(body, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))

        tk.Label(
            left,
            text="📡  Пинг DNS-серверов",
            bg=BG,
            fg=WHITE,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))

        self._ping_rows = {}
        ping_card = tk.Frame(left, bg=CARD)
        ping_card.pack(fill=tk.X)

        for name, ip, color in self.DNS_SERVERS:
            row = tk.Frame(ping_card, bg=CARD)
            row.pack(fill=tk.X, padx=10, pady=3)

            dot = tk.Label(row, text="⬤", bg=CARD, fg=SUBTEXT, font=("Segoe UI", 9))
            dot.pack(side=tk.LEFT)

            tk.Label(
                row,
                text=f"  {name}",
                bg=CARD,
                fg=TEXT,
                font=("Segoe UI", 9),
                width=20,
                anchor=tk.W,
            ).pack(side=tk.LEFT)

            tk.Label(
                row,
                text=ip if ip else "авто",
                bg=CARD,
                fg=SUBTEXT,
                font=("Consolas", 8),
                width=16,
                anchor=tk.W,
            ).pack(side=tk.LEFT)

            ping_lbl = tk.Label(
                row,
                text="—",
                bg=CARD,
                fg=SUBTEXT,
                font=("Consolas", 9, "bold"),
                width=10,
                anchor=tk.E,
            )
            ping_lbl.pack(side=tk.RIGHT)

            self._ping_rows[name] = (dot, ping_lbl, color)

        right = tk.Frame(body, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))

        tk.Label(
            right,
            text="🌐  Тест домена",
            bg=BG,
            fg=WHITE,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))

        inp_row = tk.Frame(right, bg=BG)
        inp_row.pack(fill=tk.X, pady=(0, 6))

        self.domain_var = tk.StringVar(value="chatgpt.com")
        self._entry = tk.Entry(
            inp_row,
            textvariable=self.domain_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        self._entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6, ipadx=6)
        self._entry.bind("<Return>", lambda e: self._run_domain_test())

        flat_btn(inp_row, "Проверить", self._run_domain_test, bg=ACCENT, padx=10).pack(
            side=tk.LEFT,
            padx=(6, 0),
        )

        quick = tk.Frame(right, bg=BG)
        quick.pack(fill=tk.X, pady=(0, 8))
        tk.Label(quick, text="Быстро:", bg=BG, fg=SUBTEXT, font=("Segoe UI", 8)).pack(
            side=tk.LEFT
        )
        for domain in self.QUICK_DOMAINS:
            flat_btn(
                quick,
                domain,
                lambda x=domain: self._quick_domain(x),
                bg=BORDER,
                fg=TEXT,
                padx=6,
                pady=2,
            ).pack(side=tk.LEFT, padx=2)

        dom_card = tk.Frame(right, bg=CARD)
        dom_card.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            dom_card,
            text="Результат:",
            bg=CARD,
            fg=SUBTEXT,
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, padx=10, pady=(8, 2))

        sb = tk.Scrollbar(dom_card)
        sb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 4))

        self._result_txt = tk.Text(
            dom_card,
            bg=INPUT_BG,
            fg=TEXT,
            font=("Consolas", 9),
            relief=tk.FLAT,
            state=tk.DISABLED,
            wrap=tk.WORD,
            yscrollcommand=sb.set,
        )
        self._result_txt.pack(fill=tk.BOTH, expand=True, padx=(10, 0), pady=(0, 8))
        sb.config(command=self._result_txt.yview)

        self._result_txt.tag_config("ok", foreground=GREEN)
        self._result_txt.tag_config("err", foreground=RED)
        self._result_txt.tag_config("warn", foreground=YELLOW)
        self._result_txt.tag_config(
            "head", foreground=WHITE, font=("Segoe UI", 9, "bold")
        )
        self._result_txt.tag_config("ip", foreground="#4a9eff")
        self._result_txt.tag_config("ms", foreground="#4ecca3")
        self._result_txt.tag_config("dim", foreground=SUBTEXT)

        bot = tk.Frame(self, bg=PANEL, height=44)
        bot.pack(fill=tk.X, side=tk.BOTTOM)
        bot.pack_propagate(False)

        self.btn_run = flat_btn(bot, "▶  Запустить все тесты", self._run_all, bg=GREEN)
        self.btn_run.pack(side=tk.LEFT, padx=14, pady=8)

        flat_btn(bot, "✕  Закрыть", self.destroy, bg=BORDER, fg=TEXT).pack(
            side=tk.RIGHT,
            padx=14,
            pady=8,
        )

        self._status_lbl = tk.Label(
            bot,
            text="Нажмите «Запустить все тесты»",
            bg=PANEL,
            fg=SUBTEXT,
            font=("Segoe UI", 9),
        )
        self._status_lbl.pack(side=tk.LEFT, padx=8)

    def _quick_domain(self, domain):
        self.domain_var.set(domain)
        self._run_domain_test()

    def _set_status(self, msg, color=None):
        self._status_lbl.config(text=msg, fg=color if color else SUBTEXT)

    def _write(self, text, tag=None):
        self._result_txt.config(state=tk.NORMAL)
        if tag:
            self._result_txt.insert(tk.END, text, tag)
        else:
            self._result_txt.insert(tk.END, text)
        self._result_txt.config(state=tk.DISABLED)
        self._result_txt.see(tk.END)

    def _clear_result(self):
        self._result_txt.config(state=tk.NORMAL)
        self._result_txt.delete(1.0, tk.END)
        self._result_txt.config(state=tk.DISABLED)

    def _set_ping_row(self, name, ms, error=False):
        if name not in self._ping_rows:
            return
        dot, lbl, _ = self._ping_rows[name]
        if error:
            dot.config(fg=RED)
            lbl.config(text="Недоступен", fg=RED)
        else:
            dot.config(fg=GREEN)
            lbl.config(text=f"{ms} мс", fg="#4ecca3")

    @staticmethod
    def _ping_tcp(host, port=53, timeout=3.0):
        import socket
        import time

        try:
            t0 = time.perf_counter()
            sock = socket.create_connection((host, port), timeout=timeout)
            ms = int((time.perf_counter() - t0) * 1000)
            sock.close()
            return ms
        except Exception:
            return None

    @staticmethod
    def _ping_doh(url, timeout=5.0):
        import base64
        import time

        import requests
        from dnslib import DNSRecord as DR

        try:
            t0 = time.perf_counter()
            response = requests.get(
                url,
                headers={"Accept": "application/dns-json"},
                params={"name": "google.com", "type": "A"},
                timeout=timeout,
            )
            ms = int((time.perf_counter() - t0) * 1000)
            if response.status_code == 200:
                return ms
        except Exception:
            pass

        try:
            t0 = time.perf_counter()
            req = DR.question("google.com", "A")
            b64 = base64.urlsafe_b64encode(req.pack()).rstrip(b"=").decode()
            response = requests.get(
                url,
                headers={"Accept": "application/dns-message"},
                params={"dns": b64},
                timeout=timeout,
            )
            ms = int((time.perf_counter() - t0) * 1000)
            if response.status_code == 200:
                return ms
        except Exception:
            pass

        return None

    @staticmethod
    def _resolve_domain(domain, dns_ip=None, timeout=4.0):
        import socket
        import time

        if dns_ip is None:
            try:
                t0 = time.perf_counter()
                ips = list({item[4][0] for item in socket.getaddrinfo(domain, None)})
                ms = int((time.perf_counter() - t0) * 1000)
                return ips, ms
            except Exception as exc:
                return None, str(exc)

        try:
            from dnslib import DNSRecord

            t0 = time.perf_counter()
            req = DNSRecord.question(domain, "A")
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            sock.sendto(req.pack(), (dns_ip, 53))
            data, _ = sock.recvfrom(4096)
            sock.close()
            ms = int((time.perf_counter() - t0) * 1000)
            resp = DNSRecord.parse(data)
            ips = [str(rr.rdata) for rr in resp.rr if rr.rtype == 1]
            return ips, ms
        except Exception as exc:
            return None, str(exc)

    @staticmethod
    def _resolve_doh(domain, doh_url, timeout=5.0):
        import base64
        import time

        import requests
        from dnslib import DNSRecord as DR

        t0 = time.perf_counter()

        try:
            response = requests.get(
                doh_url,
                headers={"Accept": "application/dns-json"},
                params={"name": domain, "type": "A"},
                timeout=timeout,
            )
            if response.status_code == 200 and "json" in response.headers.get("content-type", ""):
                ms = int((time.perf_counter() - t0) * 1000)
                data = response.json()
                ips = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
                if ips:
                    return ips, ms
        except Exception:
            pass

        try:
            t0 = time.perf_counter()
            req = DR.question(domain, "A")
            b64 = base64.urlsafe_b64encode(req.pack()).rstrip(b"=").decode()
            response = requests.get(
                doh_url,
                headers={"Accept": "application/dns-message"},
                params={"dns": b64},
                timeout=timeout,
            )
            response.raise_for_status()
            ms = int((time.perf_counter() - t0) * 1000)
            resp = DR.parse(response.content)
            ips = [str(rr.rdata) for rr in resp.rr if rr.rtype == 1]
            return ips, ms
        except Exception as exc:
            return None, str(exc)

    def _run_all(self):
        if self._running:
            return
        self._running = True
        self.btn_run.config(state=tk.DISABLED)
        self._set_status("⏳ Тестирование...", YELLOW)

        for _, (dot, lbl, _) in self._ping_rows.items():
            dot.config(fg=SUBTEXT)
            lbl.config(text="...", fg=SUBTEXT)

        threading.Thread(target=self._task_all, daemon=True).start()

    def _task_all(self):
        for name, ip, _ in self.DNS_SERVERS:
            if name == "xbox-dns.ru DoH":
                ms_val = self._ping_doh(XBOX_DOH_URL)
                if ms_val is not None:
                    self.after(0, lambda n=name, m=ms_val: self._set_ping_row(n, m))
                else:
                    self.after(0, lambda n=name: self._set_ping_row(n, 0, error=True))
            elif ip is None:
                ips, ms_val = self._resolve_domain("google.com")
                if ips is not None:
                    self.after(0, lambda n=name, m=ms_val: self._set_ping_row(n, m))
                else:
                    self.after(0, lambda n=name: self._set_ping_row(n, 0, error=True))
            else:
                ms_val = self._ping_tcp(ip)
                if ms_val is not None:
                    self.after(0, lambda n=name, m=ms_val: self._set_ping_row(n, m))
                else:
                    self.after(0, lambda n=name: self._set_ping_row(n, 0, error=True))

        domain = self.domain_var.get().strip()
        if domain:
            self.after(0, lambda: self._run_domain_test_inner(domain))
        else:
            self.after(0, self._done)

    def _done(self):
        self._running = False
        self.btn_run.config(state=tk.NORMAL)
        self._set_status("✓ Готово", GREEN)

    def _run_domain_test(self):
        domain = self.domain_var.get().strip()
        for prefix in ("https://", "http://", "www."):
            if domain.lower().startswith(prefix):
                domain = domain[len(prefix):]
        domain = domain.split("/")[0].lower()
        if not domain:
            return
        self.domain_var.set(domain)
        self._clear_result()
        self._set_status("⏳ Резолвинг...", YELLOW)
        threading.Thread(target=self._run_domain_test_inner, args=(domain,), daemon=True).start()

    def _run_domain_test_inner(self, domain):
        cfg = self.engine.config

        def write(text, tag=None):
            self.after(0, lambda t=text, tg=tag: self._write(t, tg))

        write(f"━━━  {domain}  ━━━\n", "head")

        write("\n🖥  Системный DNS\n", "head")
        ips, ms_val = self._resolve_domain(domain)
        if ips:
            write("  ✓  ", "ok")
            write(f"{ms_val} мс  ", "ms")
            write("→  ", "dim")
            write(", ".join(ips) + "\n", "ip")
        else:
            write(f"  ✗  Ошибка: {ms_val}\n", "err")

        write("\n☁  Cloudflare DoH\n", "head")
        ips_cf, ms_cf = self._resolve_doh(domain, "https://cloudflare-dns.com/dns-query")
        if ips_cf:
            write("  ✓  ", "ok")
            write(f"{ms_cf} мс  ", "ms")
            write("→  ", "dim")
            write(", ".join(ips_cf) + "\n", "ip")
        else:
            write(f"  ✗  Ошибка: {ms_cf}\n", "err")

        write("\n🔵  Google DoH\n", "head")
        ips_g, ms_g = self._resolve_doh(domain, "https://dns.google/dns-query")
        if ips_g:
            write("  ✓  ", "ok")
            write(f"{ms_g} мс  ", "ms")
            write("→  ", "dim")
            write(", ".join(ips_g) + "\n", "ip")
        else:
            write(f"  ✗  Ошибка: {ms_g}\n", "err")

        write("\n🎮  xbox-dns.ru DoH\n", "head")
        ips_xbd, ms_xbd = self._resolve_doh(domain, XBOX_DOH_URL)
        if ips_xbd:
            write("  ✓  ", "ok")
            write(f"{ms_xbd} мс  ", "ms")
            write("→  ", "dim")
            write(", ".join(ips_xbd) + "\n", "ip")
        else:
            write(f"  ✗  Ошибка: {ms_xbd}\n", "err")

        routed = is_domain_routed(domain, cfg)
        write("\n", "dim")
        if routed:
            write("  🔒 Домен маршрутизируется через DoH\n", "ok")
        else:
            write(
                "  ℹ  Домен НЕ в списке маршрутизации (идёт через обычный DNS)\n",
                "warn",
            )

        write("\n🔌  Проверка TCP-соединения (порт 443)\n", "head")
        test_ips = ips if ips else (ips_cf if ips_cf else [])
        test_ips_v4 = [ip for ip in test_ips if ":" not in ip][:2]
        if test_ips_v4:
            for test_ip in test_ips_v4:
                ok443 = self._check_port(test_ip, 443)
                if ok443 is True:
                    write(f"  ✓  {test_ip}:443 — ", "ok")
                    write("порт открыт, IP не заблокирован\n", "ok")
                elif ok443 is False:
                    write(f"  ✗  {test_ip}:443 — ", "err")
                    write("порт ЗАКРЫТ! Провайдер блокирует по IP\n", "err")
                else:
                    write(f"  ⚠  {test_ip}:443 — таймаут\n", "warn")
        else:
            write("  ℹ  Нет IPv4-адресов для проверки\n", "warn")

        write("\n💡  Диагноз\n", "head")
        sys_ok = bool(ips)
        doh_ok = bool(ips_cf) or bool(ips_g)
        port_ok = self._check_port(test_ips_v4[0], 443) if test_ips_v4 else None

        if not sys_ok and doh_ok:
            write("  → DNS заблокирован провайдером, но DoH работает.\n", "warn")
            write("  → Убедись что NetDocker DNS-сервер ЗАПУЩЕН и\n", "warn")
            write("    в Windows DNS установлен на 127.0.0.1\n", "warn")
        elif sys_ok and port_ok is False:
            write("  → DNS работает, но провайдер блокирует IP-адреса!\n", "err")
            write("  → DoH и NetDocker НЕ ПОМОГУТ — нужен VPN или прокси.\n", "err")
            write("  → Совет: используй браузерный DoH или VPN-расширение.\n", "warn")
        elif sys_ok and port_ok is True:
            write("  → DNS и IP доступны. Возможные причины блокировки:\n", "warn")
            write("  → 1. Chrome использует свой DoH (игнорирует системный DNS)\n", "warn")
            write("  → 2. Старый DNS-кэш — очисти: chrome://net-internals/#dns\n", "warn")
            write("  → 3. Попробуй открыть в режиме инкогнито (Ctrl+Shift+N)\n", "warn")
        elif not sys_ok and not doh_ok:
            write("  → Ни системный DNS, ни DoH не работают.\n", "err")
            write("  → Проверь подключение к интернету.\n", "err")
        else:
            write("  → Всё выглядит нормально. Проверь настройки браузера.\n", "ok")

        write("─" * 40 + "\n", "dim")
        self.after(0, self._done)

    @staticmethod
    def _check_port(host, port, timeout=3.0):
        import socket

        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            sock.close()
            return True
        except socket.timeout:
            return None
        except Exception:
            return False


class ProcessPickerDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Выбор процесса")
        self.configure(bg=PANEL)
        self.geometry("420x520")
        self.resizable(False, True)
        self.grab_set()
        self.result = None
        self._build()
        self._load()

    def _build(self):
        tk.Label(
            self,
            text="Выберите запущенный процесс",
            bg=PANEL,
            fg=TEXT,
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(14, 6))

        self.search = tk.Entry(
            self,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            relief=tk.FLAT,
            font=("Consolas", 10),
        )
        self.search.pack(fill=tk.X, padx=14, ipady=6)
        self.search.bind("<KeyRelease>", lambda e: self._filter())

        frame = tk.Frame(self, bg=PANEL)
        frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=8)

        sb = tk.Scrollbar(frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.lb = tk.Listbox(
            frame,
            yscrollcommand=sb.set,
            bg=INPUT_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=WHITE,
            font=("Consolas", 10),
            relief=tk.FLAT,
            bd=0,
            activestyle="none",
        )
        self.lb.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.lb.yview)
        self.lb.bind("<Double-Button-1>", lambda e: self._pick())

        flat_btn(self, "✓ Добавить выбранный", self._pick, bg=GREEN).pack(pady=(0, 14))

    def _load(self):
        self._all = sorted(set(proc["name"] for proc in get_running_processes() if proc.get("name")))
        self._show(self._all)

    def _filter(self):
        query = self.search.get().lower()
        self._show([proc for proc in self._all if query in proc.lower()])

    def _show(self, items):
        self.lb.delete(0, tk.END)
        for item in items:
            self.lb.insert(tk.END, item)

    def _pick(self):
        sel = self.lb.curselection()
        if sel:
            self.result = self.lb.get(sel[0])
            self.destroy()


class RestoreBackupDialog(tk.Toplevel):
    def __init__(self, parent, backups):
        super().__init__(parent)
        self.title("Восстановить backup")
        self.configure(bg=BG)
        self.geometry("520x360")
        self.resizable(True, True)
        self.grab_set()
        self.result = None
        self._backups = backups
        self._build()

    def _build(self):
        tk.Label(
            self,
            text="Выберите резервную копию настроек",
            bg=BG,
            fg=WHITE,
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor=tk.W, padx=14, pady=(14, 8))

        frame = tk.Frame(self, bg=BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))

        sb = tk.Scrollbar(frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.lb = tk.Listbox(
            frame,
            yscrollcommand=sb.set,
            bg=INPUT_BG,
            fg=TEXT,
            selectbackground=ACCENT,
            selectforeground=WHITE,
            font=("Consolas", 10),
            relief=tk.FLAT,
            bd=0,
            activestyle="none",
        )
        self.lb.pack(fill=tk.BOTH, expand=True)
        sb.config(command=self.lb.yview)
        self.lb.bind("<Double-Button-1>", lambda _e: self._choose())

        for item in self._backups:
            dt = time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(item["mtime"]))
            size_kb = max(1, item["size"] // 1024)
            self.lb.insert(tk.END, f"{dt}   {item['name']}   {size_kb} KB")

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill=tk.X, padx=14, pady=(0, 14))
        flat_btn(btn_row, "Восстановить", self._choose, bg=GREEN).pack(side=tk.RIGHT)
        flat_btn(btn_row, "Отмена", self.destroy, bg=BORDER, fg=TEXT).pack(side=tk.RIGHT, padx=(0, 6))

    def _choose(self):
        sel = self.lb.curselection()
        if not sel:
            return
        self.result = self._backups[sel[0]]["path"]
        self.destroy()


class SettingsWindow(tk.Toplevel):
    def __init__(self, parent, engine):
        super().__init__(parent)
        self.engine = engine
        self._preset_menu = None
        self._autosave_job = None
        self._autosave_suspend = False
        self.title("⚙ Настройки NetDocker")
        self.configure(bg=BG)
        self.geometry("580x600")
        # Ограничиваем ширину: контент рассчитан на ~580 px, шире становится
        # некрасиво и поля растягиваются. По высоте — без верхнего лимита,
        # но minsize гарантирует, что элементы не схлопнутся.
        self.minsize(520, 420)
        self.maxsize(720, 10000)
        self.resizable(True, True)
        # НЕ ставим grab_set(): иначе Windows не даёт свернуть окно
        # стандартной кнопкой «–». Без grab_set окно ведёт себя как
        # обычное вторичное окно — его можно сворачивать/разворачивать
        # и переключаться на главное.
        self._build()

    def _get_routed_preset_name(self):
        # Безопасно достаём stale-поля — могут не существовать,
        # если окно только начало строиться.
        opt_enabled = (
            self.optimistic_cache_enabled_var.get()
            if hasattr(self, "optimistic_cache_enabled_var") else True
        )
        stale_ttl = (
            self.stale_cache_ttl_var.get()
            if hasattr(self, "stale_cache_ttl_var") else "3600"
        )
        return get_routed_preset_name(
            self.routed_cache_enabled_var.get(),
            self.routed_cache_ttl_var.get(),
            self.routed_reply_ttl_var.get(),
            optimistic_cache_enabled=opt_enabled,
            stale_cache_ttl=stale_ttl,
        )

    def _update_preset_display(self, *_args):
        self.preset_display_var.set(f"{self._get_routed_preset_name()} ▾")

    def _bind_preset_watchers(self):
        watched_vars = [
            self.port_var,
            self.fallback_var,
            self.fallback6_var,
            self.route_all_var,
            self.ipv6_var,
            self.upstream_mode_var,
            self.routed_cache_enabled_var,
            self.routed_cache_ttl_var,
            self.routed_reply_ttl_var,
            self.optimistic_cache_enabled_var,
            self.stale_cache_ttl_var,
        ]
        for var in watched_vars:
            var.trace_add("write", self._schedule_autosave)
        # Подпись на кнопке upstream-стратегии обновляется отдельно.
        self.upstream_mode_var.trace_add("write", self._update_upstream_mode_label)
        self._update_upstream_mode_label()

        for var in (
            self.routed_cache_enabled_var,
            self.routed_cache_ttl_var,
            self.routed_reply_ttl_var,
            self.optimistic_cache_enabled_var,
            self.stale_cache_ttl_var,
        ):
            var.trace_add("write", self._update_preset_display)
        # Тогл/поле для stale_ttl активны только когда optimistic включён.
        self.optimistic_cache_enabled_var.trace_add("write", self._update_optimistic_ui_state)
        self._update_preset_display()
        self._update_optimistic_ui_state()

    def _build_preset_menu(self):
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=CARD,
            fg=TEXT,
            activebackground=ACCENT,
            activeforeground=WHITE,
            font=("Segoe UI", 9),
            bd=0,
        )
        current_name = self._get_routed_preset_name()
        for name, _values, _desc in ROUTED_PRESETS:
            prefix = "✓ " if current_name == name else "   "
            menu.add_command(
                label=f"{prefix}{name}",
                command=lambda n=name: self._apply_routed_preset(n),
            )
        self._preset_menu = menu
        return menu

    def _show_preset_popup(self):
        menu = self._build_preset_menu()
        x = self.preset_btn.winfo_rootx()
        y = self.preset_btn.winfo_rooty() + self.preset_btn.winfo_height() + 2
        menu.tk_popup(x, y)

    def _wrapping_hint(self, parent, text, padx=12, pady=(0, 10), side_padding=24):
        """Многострочная подпись-подсказка, которая АВТО-переносится по ширине родителя.

        Проблема: обычный tk.Label с justify=LEFT и жёсткими "\\n" при узком
        окне обрезает текст справа. wraplength решает это, но его надо
        пересчитывать на каждый ресайз родителя.

        Этот хелпер сам подписывается на <Configure> родителя и пересчитывает
        wraplength = (ширина родителя - side_padding). side_padding учитывает
        внутренние отступы LabelFrame'а, чтобы текст не упирался в правый край.
        """
        lbl = tk.Label(
            parent, text=text,
            bg=CARD, fg=SUBTEXT, font=("Segoe UI", 8),
            justify=tk.LEFT, anchor=tk.W,
            # Стартовое значение wraplength — потом будет пересчитано.
            wraplength=400,
        )
        lbl.pack(anchor=tk.W, fill=tk.X, padx=padx, pady=pady)

        def _on_parent_resize(event):
            new_wrap = max(120, event.width - side_padding)
            if lbl.cget("wraplength") != new_wrap:
                lbl.configure(wraplength=new_wrap)

        parent.bind("<Configure>", _on_parent_resize, add="+")
        return lbl

    # ── Меню выбора upstream-стратегии (sequential/parallel/fastest) ──────
    _UPSTREAM_MODE_LABELS = [
        ("sequential", "По очереди"),
        ("parallel",   "Параллельно"),
        ("fastest",    "Самый быстрый"),
    ]

    def _upstream_mode_label(self, key):
        for k, label in self._UPSTREAM_MODE_LABELS:
            if k == key:
                return label
        return key

    def _update_upstream_mode_label(self, *_args):
        if not hasattr(self, "upstream_mode_display"):
            return
        label = self._upstream_mode_label(self.upstream_mode_var.get())
        self.upstream_mode_display.set(f"{label}  ▾")

    def _show_upstream_mode_menu(self):
        menu = tk.Menu(
            self, tearoff=0,
            bg=CARD, fg=TEXT,
            activebackground=ACCENT, activeforeground=WHITE,
            font=("Segoe UI", 9), bd=0,
        )
        current = self.upstream_mode_var.get()
        for key, label in self._UPSTREAM_MODE_LABELS:
            prefix = "✓ " if key == current else "   "
            menu.add_command(
                label=f"{prefix}{label}",
                command=lambda k=key: self._set_upstream_mode(k),
            )
        x = self.upstream_mode_btn.winfo_rootx()
        y = self.upstream_mode_btn.winfo_rooty() + self.upstream_mode_btn.winfo_height() + 2
        menu.tk_popup(x, y)

    def _set_upstream_mode(self, key):
        if self.upstream_mode_var.get() == key:
            return
        self.upstream_mode_var.set(key)
        # autosave подтянется через trace на upstream_mode_var.

    def _apply_routed_preset(self, preset_name):
        preset_map = get_routed_preset_map()
        values = preset_map[preset_name]

        self._autosave_suspend = True
        self.routed_cache_enabled_var.set(values["routed_cache_enabled"])
        self.routed_cache_ttl_var.set(str(values["routed_cache_ttl"]))
        self.routed_reply_ttl_var.set(str(values["routed_reply_ttl"]))
        # Пресет тянет и optimistic-настройки (если новые поля есть в пресете).
        if "optimistic_cache_enabled" in values:
            self.optimistic_cache_enabled_var.set(values["optimistic_cache_enabled"])
        if "stale_cache_ttl" in values:
            self.stale_cache_ttl_var.set(str(values["stale_cache_ttl"]))
        self._autosave_suspend = False
        self._update_optimistic_ui_state()

        if self._auto_save_now(show_message=False):
            self._update_preset_display()
            if self.engine.running and hasattr(self.winfo_toplevel(), "ctrl"):
                if messagebox.askyesno(
                    "Пресет применён",
                    f"Режим «{preset_name}» сохранён.\n\nПерезапустить DNS сейчас?",
                    parent=self,
                ):
                    self.winfo_toplevel().ctrl._restart()
            else:
                self._set_form_status(f"Режим «{preset_name}» сохранён", GREEN)

    def _set_form_status(self, text, color=SUBTEXT):
        if hasattr(self, "status_lbl"):
            self.status_lbl.config(text=text, fg=color)

    def _update_optimistic_ui_state(self, *_args):
        """Гасит поле «Stale TTL» и слайдер, когда optimistic-кэш выключен —
        чтобы было визуально понятно, что число ни на что не влияет.
        """
        if not hasattr(self, "stale_ttl_entry"):
            return
        enabled = bool(self.optimistic_cache_enabled_var.get())
        state = "normal" if enabled else "disabled"
        try:
            self.stale_ttl_entry.config(state=state)
            self.stale_ttl_label.config(fg=TEXT if enabled else SUBTEXT)
        except Exception:
            pass
        if hasattr(self, "stale_slider"):
            # У Canvas нет state, поэтому просто гасим обработчики и курсор.
            try:
                if enabled:
                    self.stale_slider.configure(cursor="hand2")
                    # Возвращаем активный цвет трека/handle (вызовом перерисовки).
                    self.stale_slider._redraw()
                else:
                    self.stale_slider.configure(cursor="arrow")
            except Exception:
                pass

    def _on_stale_slider_change(self, value):
        """Пользователь подвигал слайдер → синхронизируем StringVar.

        Не дергаем autosave вручную — он сам подцепится через trace,
        который привязан к stale_cache_ttl_var.
        """
        # Не делаем ничего, если optimistic выключен (защита от случайного клика).
        if not bool(self.optimistic_cache_enabled_var.get()):
            return
        # Записываем строкой, потому что поле ввода тоже StringVar.
        new_text = str(int(value))
        if self.stale_cache_ttl_var.get() != new_text:
            self.stale_cache_ttl_var.set(new_text)

    def _sync_slider_from_var(self, *_args):
        """Пользователь ввёл число в поле → подвинуть слайдер.

        Используем _suspend_callback, чтобы не словить рекурсию
        (slider → var → slider → ...).
        """
        if not hasattr(self, "stale_slider"):
            return
        try:
            value = int(self.stale_cache_ttl_var.get())
        except Exception:
            return
        if value == self.stale_slider.get_value():
            return
        self.stale_slider._suspend_callback = True
        try:
            self.stale_slider.set_value(value)
        finally:
            self.stale_slider._suspend_callback = False

    def _collect_form_to_cfg(self):
        cfg = dict(self.engine.config)
        cfg["listen_port"] = int(self.port_var.get())
        cfg["fallback_dns"] = self.fallback_var.get().strip()
        cfg["fallback_dns6"] = self.fallback6_var.get().strip()
        cfg["route_all"] = self.route_all_var.get()
        cfg["enable_ipv6"] = self.ipv6_var.get()
        cfg["routed_cache_enabled"] = self.routed_cache_enabled_var.get()
        cfg["routed_cache_ttl"] = int(self.routed_cache_ttl_var.get())
        cfg["routed_reply_ttl"] = int(self.routed_reply_ttl_var.get())
        cfg["optimistic_cache_enabled"] = self.optimistic_cache_enabled_var.get()
        cfg["stale_cache_ttl"] = int(self.stale_cache_ttl_var.get())
        cfg["upstream_mode"] = (self.upstream_mode_var.get() or "parallel").strip().lower()
        return cfg

    def _auto_save_now(self, show_message=False):
        if self._autosave_job is not None:
            try:
                self.after_cancel(self._autosave_job)
            except Exception:
                pass
            self._autosave_job = None

        try:
            cfg = self._collect_form_to_cfg()
        except ValueError:
            self._set_form_status("Проверь числовые поля: порт и TTL", RED)
            return False

        save_config(cfg)
        self.engine.reload_config()
        self._set_form_status("Настройки сохранены автоматически", GREEN)
        if show_message:
            messagebox.showinfo("Готово", "Настройки сохранены", parent=self)
        return True

    def _schedule_autosave(self, *_args):
        if self._autosave_suspend:
            return
        if self._autosave_job is not None:
            try:
                self.after_cancel(self._autosave_job)
            except Exception:
                pass
        self._set_form_status("Сохраняю...", YELLOW)
        self._autosave_job = self.after(500, self._auto_save_now)

    def _apply_cfg_to_form(self, cfg):
        self._autosave_suspend = True
        self.port_var.set(str(cfg.get("listen_port", DEFAULT_CONFIG["listen_port"])))
        self.fallback_var.set(cfg.get("fallback_dns", DEFAULT_CONFIG["fallback_dns"]))
        self.fallback6_var.set(cfg.get("fallback_dns6", DEFAULT_CONFIG["fallback_dns6"]))
        self.route_all_var.set(cfg.get("route_all", DEFAULT_CONFIG["route_all"]))
        self.ipv6_var.set(cfg.get("enable_ipv6", DEFAULT_CONFIG["enable_ipv6"]))
        self.routed_cache_enabled_var.set(cfg.get("routed_cache_enabled", DEFAULT_CONFIG["routed_cache_enabled"]))
        self.routed_cache_ttl_var.set(str(cfg.get("routed_cache_ttl", DEFAULT_CONFIG["routed_cache_ttl"])))
        self.routed_reply_ttl_var.set(str(cfg.get("routed_reply_ttl", DEFAULT_CONFIG["routed_reply_ttl"])))
        self.optimistic_cache_enabled_var.set(
            cfg.get("optimistic_cache_enabled", DEFAULT_CONFIG["optimistic_cache_enabled"])
        )
        self.stale_cache_ttl_var.set(str(cfg.get("stale_cache_ttl", DEFAULT_CONFIG["stale_cache_ttl"])))
        self.upstream_mode_var.set(cfg.get("upstream_mode", DEFAULT_CONFIG["upstream_mode"]))
        self._autosave_suspend = False
        self._update_preset_display()
        self._update_optimistic_ui_state()
        self._update_upstream_mode_label()

    def _reset_defaults(self):
        if not messagebox.askyesno(
            "Сбросить настройки",
            "Сбросить все настройки этого окна к значениям по умолчанию?",
            parent=self,
        ):
            return

        self._apply_cfg_to_form(DEFAULT_CONFIG)
        self._auto_save_now(show_message=False)
        self._set_form_status("Настройки сброшены к значениям по умолчанию", GREEN)

    def _create_backup(self):
        if not self._auto_save_now(show_message=False):
            return
        path = create_config_backup(self.engine.config)
        self._set_form_status(f"Backup сохранён: {os.path.basename(path)}", GREEN)
        messagebox.showinfo(
            "Резервная копия создана",
            f"Backup настроек сохранён:\n{path}",
            parent=self,
        )

    def _restore_backup(self):
        backups = list_config_backups()
        if not backups:
            messagebox.showinfo(
                "Нет backup",
                "Резервные копии настроек не найдены.",
                parent=self,
            )
            return

        dlg = RestoreBackupDialog(self, backups)
        self.wait_window(dlg)
        if not dlg.result:
            return

        try:
            cfg = load_config_backup(dlg.result)
        except Exception as exc:
            messagebox.showerror("Ошибка", f"Не удалось восстановить backup:\n{exc}", parent=self)
            return

        save_config(cfg)
        self.engine.reload_config()
        self._apply_cfg_to_form(self.engine.config)
        self._set_form_status(f"Восстановлен backup: {os.path.basename(dlg.result)}", GREEN)

        if self.engine.running and hasattr(self.winfo_toplevel(), "ctrl"):
            if messagebox.askyesno(
                "Backup восстановлен",
                "Настройки восстановлены.\n\nПерезапустить DNS сейчас?",
                parent=self,
            ):
                self.winfo_toplevel().ctrl._restart()
        else:
            messagebox.showinfo(
                "Backup восстановлен",
                f"Настройки восстановлены из:\n{dlg.result}",
                parent=self,
            )

    def _build(self):
        hdr = tk.Frame(self, bg=PANEL, height=44)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(
            hdr,
            text="⚙  Настройки",
            bg=PANEL,
            fg=WHITE,
            font=("Segoe UI", 13, "bold"),
        ).pack(side=tk.LEFT, padx=16)
        flat_btn(hdr, "↺ Сбросить", self._reset_defaults,
                 bg=BORDER, fg=TEXT, padx=10, pady=4).pack(side=tk.RIGHT, padx=(0, 12), pady=8)
        flat_btn(hdr, "⤒ Восстановить", self._restore_backup,
                 bg=BORDER, fg=TEXT, padx=10, pady=4).pack(side=tk.RIGHT, padx=(0, 6), pady=8)
        flat_btn(hdr, "⤓ Резервная копия", self._create_backup,
                 bg=ACCENT, fg=WHITE, padx=10, pady=4).pack(side=tk.RIGHT, padx=(0, 6), pady=8)

        # ── Скроллируемое тело ──────────────────────────────────────────────
        # Делаем canvas + вертикальный scrollbar, чтобы контент любой высоты
        # можно было крутить мышкой/колесом, как страницу в браузере.
        # Сам контент кладём в _scroll_inner — для внешнего кода это и есть
        # «body», поэтому переменная так и названа.
        scroll_wrap = tk.Frame(self, bg=BG)
        scroll_wrap.pack(fill=tk.BOTH, expand=True)

        self._scroll_canvas = tk.Canvas(
            scroll_wrap, bg=BG, highlightthickness=0, bd=0,
        )
        self._scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._scrollbar = tk.Scrollbar(
            scroll_wrap, orient=tk.VERTICAL, command=self._scroll_canvas.yview,
        )
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._scroll_canvas.configure(yscrollcommand=self._scrollbar.set)

        body = tk.Frame(self._scroll_canvas, bg=BG)
        # Кладём body в canvas через create_window и запоминаем window-id —
        # чтобы при ресайзе окна растягивать ширину body под canvas
        # (иначе он остался бы шириной 1 px и контент бы прижался влево).
        self._body_window_id = self._scroll_canvas.create_window(
            (0, 0), window=body, anchor="nw",
        )

        def _on_body_configure(_event):
            # Контент изменил высоту → пересчитать scrollregion.
            self._scroll_canvas.configure(scrollregion=self._scroll_canvas.bbox("all"))

        def _on_canvas_configure(event):
            # Canvas изменил ширину → растянуть body на ту же ширину
            # (минус padding, чтобы не залезть под scrollbar).
            self._scroll_canvas.itemconfigure(self._body_window_id, width=event.width)

        body.bind("<Configure>", _on_body_configure)
        self._scroll_canvas.bind("<Configure>", _on_canvas_configure)

        # ── Прокрутка колёсиком мыши ────────────────────────────────────────
        # На Windows колёсико шлёт <MouseWheel> с event.delta = ±120 за щелчок.
        # На X11 (Linux) — Button-4 (вверх) и Button-5 (вниз).
        # Привязываем bind_all только когда курсор над нашим окном,
        # чтобы не "красть" скролл у других окон приложения.
        def _on_mousewheel(event):
            if hasattr(event, "delta") and event.delta:
                self._scroll_canvas.yview_scroll(int(-event.delta / 120), "units")
            elif getattr(event, "num", None) == 4:
                self._scroll_canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                self._scroll_canvas.yview_scroll(3, "units")
            return "break"

        def _bind_wheel(_e=None):
            self.bind_all("<MouseWheel>", _on_mousewheel)
            self.bind_all("<Button-4>", _on_mousewheel)
            self.bind_all("<Button-5>", _on_mousewheel)

        def _unbind_wheel(_e=None):
            try:
                self.unbind_all("<MouseWheel>")
                self.unbind_all("<Button-4>")
                self.unbind_all("<Button-5>")
            except Exception:
                pass

        # Когда мышь заходит в окно настроек — перехватываем колёсико,
        # когда уходит — отпускаем, чтобы скролл вернулся главному окну.
        self.bind("<Enter>", _bind_wheel)
        self.bind("<Leave>", _unbind_wheel)
        self.bind("<FocusIn>", _bind_wheel)
        self.bind("<FocusOut>", _unbind_wheel)
        self.bind("<Destroy>", _unbind_wheel)

        # Сам body имеет внутренние отступы; они раньше задавались на pack().
        body_padding = tk.Frame(body, bg=BG)
        body_padding.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)
        body = body_padding  # дальше старый код работает с переменной body как было

        sec1 = tk.LabelFrame(
            body,
            text=" DNS-сервер ",
            bg=CARD,
            fg=WHITE,
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        sec1.pack(fill=tk.X, pady=(0, 10))

        row1 = tk.Frame(sec1, bg=CARD)
        row1.pack(fill=tk.X, padx=12, pady=8)
        tk.Label(row1, text="Порт:", bg=CARD, fg=TEXT, font=("Segoe UI", 9), width=10, anchor=tk.W).pack(side=tk.LEFT)
        self.port_var = tk.StringVar(value=str(self.engine.config.get("listen_port", 53)))
        tk.Entry(
            row1,
            textvariable=self.port_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            font=("Consolas", 9),
            width=8,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, ipady=4)

        row2 = tk.Frame(sec1, bg=CARD)
        row2.pack(fill=tk.X, padx=12, pady=(0, 6))
        tk.Label(row2, text="Fallback IPv4:", bg=CARD, fg=TEXT, font=("Segoe UI", 9), width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.fallback_var = tk.StringVar(value=self.engine.config.get("fallback_dns", "8.8.8.8"))
        tk.Entry(
            row2,
            textvariable=self.fallback_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            font=("Consolas", 9),
            width=16,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, ipady=4)

        row3 = tk.Frame(sec1, bg=CARD)
        row3.pack(fill=tk.X, padx=12, pady=(0, 8))
        tk.Label(row3, text="Fallback IPv6:", bg=CARD, fg=TEXT, font=("Segoe UI", 9), width=12, anchor=tk.W).pack(side=tk.LEFT)
        self.fallback6_var = tk.StringVar(value=self.engine.config.get("fallback_dns6", ""))
        tk.Entry(
            row3,
            textvariable=self.fallback6_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            font=("Consolas", 9),
            width=24,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, ipady=4)

        sec2 = tk.LabelFrame(
            body,
            text=" Поведение ",
            bg=CARD,
            fg=WHITE,
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        sec2.pack(fill=tk.X, pady=(0, 10))

        self.route_all_var = tk.BooleanVar(value=self.engine.config.get("route_all", False))
        try:
            from profile_utils import get_active_dns_profile
            _active_name = get_active_dns_profile(self.engine.config).get("name", "выбранный профиль")
        except Exception:
            _active_name = "выбранный профиль"
        tk.Checkbutton(
            sec2,
            text=f"Маршрутизировать ВСЕ домены через выбранный профиль ({_active_name})",
            variable=self.route_all_var,
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, padx=12, pady=8)

        self.ipv6_var = tk.BooleanVar(value=self.engine.config.get("enable_ipv6", True))
        tk.Checkbutton(
            sec2,
            text="Включить IPv6 DNS сервер",
            variable=self.ipv6_var,
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, padx=12, pady=(0, 8))

        # ── Автозапуск с Windows ────────────────────────────────────────────
        try:
            import autostart
            self._autostart_supported = autostart.is_supported()
            autostart_now = autostart.is_enabled()
        except Exception:
            self._autostart_supported = False
            autostart_now = False
        self.autostart_var = tk.BooleanVar(value=autostart_now)
        chk_autostart = tk.Checkbutton(
            sec2,
            text="Запускать NetDocker при включении Windows",
            variable=self.autostart_var,
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            font=("Segoe UI", 9),
        )
        chk_autostart.pack(anchor=tk.W, padx=12, pady=(0, 8))
        if not self._autostart_supported:
            chk_autostart.config(state=tk.DISABLED, text="Автозапуск (только Windows)")

        # ── Стратегия опроса нескольких upstream-серверов ───────────────────
        # Те же primary/secondary/DoH можно опрашивать по очереди или сразу.
        # "Параллельно" даёт реальное ускорение в 2-3 раза на нестабильной сети.
        self.upstream_mode_var = tk.StringVar(
            value=self.engine.config.get("upstream_mode", "parallel")
        )
        upstream_row = tk.Frame(sec2, bg=CARD)
        upstream_row.pack(fill=tk.X, padx=12, pady=(0, 8))
        tk.Label(upstream_row, text="Стратегия upstream:", bg=CARD, fg=TEXT,
                 font=("Segoe UI", 9), width=18, anchor=tk.W).pack(side=tk.LEFT)
        upstream_wrap = tk.Frame(
            upstream_row, bg=INPUT_BG,
            highlightbackground=BORDER, highlightthickness=1,
        )
        upstream_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.upstream_mode_display = tk.StringVar()
        self.upstream_mode_btn = tk.Button(
            upstream_wrap,
            textvariable=self.upstream_mode_display,
            command=self._show_upstream_mode_menu,
            bg=INPUT_BG, fg=TEXT,
            activebackground=INPUT_BG, activeforeground=WHITE,
            relief=tk.FLAT, bd=0, anchor=tk.W, cursor="hand2",
            font=("Segoe UI", 9), padx=8, pady=6,
        )
        self.upstream_mode_btn.pack(fill=tk.X)
        self._wrapping_hint(
            sec2,
            "По очереди — старое поведение: primary → secondary → DoH. "
            "Параллельно — все upstream'ы одновременно, берём первый ответ (рекомендуется). "
            "Самый быстрый — автоматически выбирает лидера по статистике, "
            "периодически перепроверяет.",
            pady=(0, 10),
        )

        self.routed_cache_enabled_var = tk.BooleanVar(
            value=self.engine.config.get("routed_cache_enabled", True)
        )
        self.routed_cache_ttl_var = tk.StringVar(
            value=str(self.engine.config.get("routed_cache_ttl", 5))
        )
        self.routed_reply_ttl_var = tk.StringVar(
            value=str(self.engine.config.get("routed_reply_ttl", 1))
        )
        self.optimistic_cache_enabled_var = tk.BooleanVar(
            value=self.engine.config.get("optimistic_cache_enabled", True)
        )
        self.stale_cache_ttl_var = tk.StringVar(
            value=str(self.engine.config.get("stale_cache_ttl", 3600))
        )
        self.preset_display_var = tk.StringVar()

        sec3 = tk.LabelFrame(
            body,
            text=" Routed-домены: кэш и TTL ",
            bg=CARD,
            fg=WHITE,
            font=("Segoe UI", 9, "bold"),
            relief=tk.FLAT,
            bd=0,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        sec3.pack(fill=tk.X, pady=(0, 10))

        preset_row = tk.Frame(sec3, bg=CARD)
        preset_row.pack(fill=tk.X, padx=12, pady=(8, 8))
        tk.Label(preset_row, text="Режим:", bg=CARD, fg=TEXT,
                 font=("Segoe UI", 9), width=12, anchor=tk.W).pack(side=tk.LEFT)
        preset_wrap = tk.Frame(
            preset_row,
            bg=INPUT_BG,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        preset_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.preset_btn = tk.Button(
            preset_wrap,
            textvariable=self.preset_display_var,
            command=self._show_preset_popup,
            bg=INPUT_BG,
            fg=TEXT,
            activebackground=INPUT_BG,
            activeforeground=WHITE,
            relief=tk.FLAT,
            bd=0,
            anchor=tk.W,
            cursor="hand2",
            font=("Segoe UI", 9),
            padx=8,
            pady=6,
        )
        self.preset_btn.pack(fill=tk.X)

        tk.Checkbutton(
            sec3,
            text="Включить внутренний кэш NetDocker для routed-доменов",
            variable=self.routed_cache_enabled_var,
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, padx=12, pady=(0, 6))

        routed_row1 = tk.Frame(sec3, bg=CARD)
        routed_row1.pack(fill=tk.X, padx=12, pady=(0, 6))
        tk.Label(routed_row1, text="TTL кэша (сек):", bg=CARD, fg=TEXT,
                 font=("Segoe UI", 9), width=18, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(
            routed_row1,
            textvariable=self.routed_cache_ttl_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            font=("Consolas", 9),
            width=8,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, ipady=4)

        routed_row2 = tk.Frame(sec3, bg=CARD)
        routed_row2.pack(fill=tk.X, padx=12, pady=(0, 8))
        tk.Label(routed_row2, text="TTL ответа браузеру:", bg=CARD, fg=TEXT,
                 font=("Segoe UI", 9), width=18, anchor=tk.W).pack(side=tk.LEFT)
        tk.Entry(
            routed_row2,
            textvariable=self.routed_reply_ttl_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            font=("Consolas", 9),
            width=8,
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, ipady=4)

        self._wrapping_hint(
            sec3,
            "0 = браузер должен как можно чаще спрашивать DNS заново. "
            "Короткий TTL ответа уменьшает залипание старых адресов, "
            "а TTL кэша управляет тем, как долго сам NetDocker держит ответ в памяти.",
            pady=(0, 10),
        )

        # ── Optimistic cache (stale-while-revalidate) ──────────────────────
        # Лёгкий разделитель внутри той же карточки, чтобы тогл визуально был
        # связан с routed-кэшом, но не сливался с ним.
        tk.Frame(sec3, bg=BORDER, height=1).pack(fill=tk.X, padx=12, pady=(0, 8))

        self.optimistic_chk = tk.Checkbutton(
            sec3,
            text="⚡ Optimistic cache (мгновенные ответы из «просроченного» кэша)",
            variable=self.optimistic_cache_enabled_var,
            bg=CARD,
            fg=TEXT,
            selectcolor=INPUT_BG,
            activebackground=CARD,
            font=("Segoe UI", 9),
        )
        self.optimistic_chk.pack(anchor=tk.W, padx=12, pady=(0, 4))

        optim_row = tk.Frame(sec3, bg=CARD)
        optim_row.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.stale_ttl_label = tk.Label(
            optim_row, text="Stale TTL (сек):", bg=CARD, fg=TEXT,
            font=("Segoe UI", 9), width=18, anchor=tk.W,
        )
        self.stale_ttl_label.pack(side=tk.LEFT)
        self.stale_ttl_entry = tk.Entry(
            optim_row,
            textvariable=self.stale_cache_ttl_var,
            bg=INPUT_BG,
            fg=TEXT,
            insertbackground=WHITE,
            disabledbackground=INPUT_BG,
            disabledforeground=SUBTEXT,
            font=("Consolas", 9),
            width=8,
            relief=tk.FLAT,
        )
        self.stale_ttl_entry.pack(side=tk.LEFT, ipady=4)
        tk.Label(
            optim_row, text="(0 = выкл, до 86400 = 24 ч)",
            bg=CARD, fg=SUBTEXT, font=("Segoe UI", 8),
        ).pack(side=tk.LEFT, padx=(8, 0))

        # ── Слайдер с маркерами пресетов под полем Stale TTL ───────────────
        # 3 маркера: 0 (Совместимый) / 3600 = 1 ч (Рекомендуемый) /
        # 86400 = 24 ч (Скоростной). Между ними значения интерполируются
        # секционно линейно — иначе при общей линейной шкале маркер 3600
        # стоял бы почти у самого края, и им было бы неудобно пользоваться.
        slider_row = tk.Frame(sec3, bg=CARD)
        slider_row.pack(fill=tk.X, padx=12, pady=(0, 8))
        self.stale_slider = PresetSlider(
            slider_row,
            presets=[
                (0, "Совместимый"),
                (3600, "Рекомендуемый (1ч)"),
                (86400, "Скоростной (24ч)"),
            ],
            on_change=self._on_stale_slider_change,
            width=520,
            height=46,
            bg=CARD,
        )
        self.stale_slider.pack(fill=tk.X)
        # Начальная синхронизация: слайдер → значение из поля.
        try:
            self.stale_slider.set_value(int(self.stale_cache_ttl_var.get()))
        except Exception:
            pass
        # Обратная связь: поле ввода → слайдер.
        # Делаем это после создания слайдера, иначе при первом trace
        # атрибута stale_slider ещё не существует.
        self.stale_cache_ttl_var.trace_add("write", self._sync_slider_from_var)

        self._wrapping_hint(
            sec3,
            "Когда обычный TTL ответа истёк, NetDocker может отдать просроченный "
            "ответ моментально и в фоне обновить его — это даёт ~0 мс задержку "
            "вместо 20–100 мс. Stale TTL = на сколько секунд после истечения TTL "
            "ещё разрешено отдавать просроченный ответ.",
            pady=(0, 10),
        )

        self._bind_preset_watchers()

        self.status_lbl = tk.Label(
            body,
            text="Настройки сохраняются автоматически",
            bg=BG,
            fg=SUBTEXT,
            font=("Segoe UI", 8),
            justify=tk.LEFT,
        )
        self.status_lbl.pack(anchor=tk.W, pady=(4, 0))

    def _save(self):
        cfg = self.engine.config
        try:
            cfg["listen_port"] = int(self.port_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "Порт должен быть числом")
            return

        cfg["fallback_dns"] = self.fallback_var.get().strip()
        cfg["fallback_dns6"] = self.fallback6_var.get().strip()
        cfg["route_all"] = self.route_all_var.get()
        cfg["enable_ipv6"] = self.ipv6_var.get()
        cfg["routed_cache_enabled"] = self.routed_cache_enabled_var.get()
        try:
            cfg["routed_cache_ttl"] = int(self.routed_cache_ttl_var.get())
            cfg["routed_reply_ttl"] = int(self.routed_reply_ttl_var.get())
        except ValueError:
            messagebox.showerror("Ошибка", "TTL routed-доменов должен быть числом")
            return
        save_config(cfg)
        self.engine.reload_config()

        # Применяем автозапуск с Windows (если поддерживается)
        autostart_msg = ""
        if getattr(self, "_autostart_supported", False):
            try:
                import autostart
                if self.autostart_var.get() != autostart.is_enabled():
                    ok, msg = autostart.set_enabled(self.autostart_var.get())
                    autostart_msg = f"\n{msg}" if ok else f"\n⚠ {msg}"
            except Exception as exc:
                autostart_msg = f"\n⚠ Автозапуск: {exc}"

        messagebox.showinfo("Готово",
            "Настройки сохранены.\nПерезапустите DNS для применения." + autostart_msg)
        self.destroy()
