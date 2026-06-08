"""
NetDocker - Точка входа
Запускает GUI или консольный режим.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def run_gui():
    from gui import main
    main()


def run_cli(args):
    import signal
    import time

    from dns_server import get_instance
    from profile_utils import get_active_dns_profile

    engine = get_instance()

    if args.add_domain:
        for domain in args.add_domain:
            engine.add_domain(domain)
        print(f"Добавлены домены: {args.add_domain}")

    if args.remove_domain:
        for domain in args.remove_domain:
            engine.remove_domain(domain)
        print(f"Удалены домены: {args.remove_domain}")

    if args.add_process:
        for process in args.add_process:
            engine.add_process(process)
        print(f"Добавлены процессы: {args.add_process}")

    if args.remove_process:
        for process in args.remove_process:
            engine.remove_process(process)
        print(f"Удалены процессы: {args.remove_process}")

    if args.start or args.daemon:
        print("Запуск NetDocker DNS-сервера...")
        result = engine.start()
        if result:
            mode = engine.config.get("xbox_dns_mode", "udp")
            profile = get_active_dns_profile(engine.config)
            print(f"DNS-сервер запущен на {engine.config['listen_host']}:{engine.config['listen_port']}")
            print(f"Активный профиль: {profile.get('name')}")
            print(f"Режим профиля: {mode}")
            if mode == "doh":
                print(f"DoH URL: {profile.get('doh_url') or 'не задан'}")
            else:
                print(f"UDP DNS: {profile.get('ipv4_primary') or '-'}, {profile.get('ipv4_secondary') or '-'}")
            print("Маршрутизируемые домены:", engine.config["routed_domains"])
            print("\nНажмите Ctrl+C для остановки")

            def handler(sig, frame):
                print("\nОстановка...")
                engine.stop()
                sys.exit(0)

            signal.signal(signal.SIGINT, handler)
            while True:
                time.sleep(1)
        else:
            print("Ошибка запуска DNS-сервера")
            sys.exit(1)

    if args.list:
        cfg = engine.config
        print("\n=== NetDocker конфигурация ===")
        profile = get_active_dns_profile(cfg)
        print(f"Активный профиль: {profile.get('name')}")
        print(f"Режим профиля: {cfg.get('xbox_dns_mode', 'udp')}")
        print(f"Profile IPv4: {profile.get('ipv4_primary') or '-'} / {profile.get('ipv4_secondary') or '-'}")
        print(f"Profile IPv6: {profile.get('ipv6_primary') or '-'} / {profile.get('ipv6_secondary') or '-'}")
        print(f"Profile DoH: {profile.get('doh_url') or 'не задан'}")
        print(f"Profile DoT: {profile.get('dot_host') or profile.get('dot_ip') or 'не задан'}:{profile.get('dot_port', 853)}")
        doq_host = profile.get('doq_host') or profile.get('doq_ip') or 'не задан'
        try:
            from dns_transports import doq_available
            doq_note = "" if doq_available() else "  (нужен пакет aioquic)"
        except Exception:
            doq_note = ""
        print(f"Profile DoQ: {doq_host}:{profile.get('doq_port', 853)}{doq_note}")
        stamp = profile.get('dnscrypt_stamp') or 'не задан'
        try:
            from dnscrypt import dnscrypt_available
            dc_note = "" if dnscrypt_available() else "  (нужен пакет pynacl)"
        except Exception:
            dc_note = ""
        print(f"Profile DNSCrypt: {stamp}{dc_note}")
        print(f"Fallback DNS IPv4: {cfg['fallback_dns']}")
        print(f"Fallback DNS IPv6: {cfg.get('fallback_dns6') or 'не задан'}")
        print(f"Слушает на: {cfg['listen_host']}:{cfg['listen_port']}")
        print(f"IPv6 включён: {'да' if cfg.get('enable_ipv6', True) else 'нет'}")
        print(f"Routed cache enabled: {'да' if cfg.get('routed_cache_enabled', True) else 'нет'}")
        print(f"Routed cache TTL: {cfg.get('routed_cache_ttl', 5)} сек")
        print(f"Routed reply TTL: {cfg.get('routed_reply_ttl', 1)} сек")
        print(f"\nМаршрутизируемые домены ({len(cfg['routed_domains'])}):")
        for domain in cfg["routed_domains"]:
            print(f"  - {domain}")
        print(f"\nСписок процессов для маршрутизации по приложениям ({len(cfg['routed_processes'])}):")
        for process in cfg["routed_processes"]:
            print(f"  - {process}")



def main():
    parser = argparse.ArgumentParser(
        description="NetDocker - Умный DNS-роутер с DoH поддержкой",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python main.py                                    # Запуск GUI
  python main.py --cli --start                      # Запуск в консольном режиме
  python main.py --cli --list                       # Показать конфигурацию
  python main.py --cli --add-domain chatgpt.com     # Добавить домен
  python main.py --cli --add-process chrome.exe     # Добавить процесс в список маршрутизации по приложениям
        """,
    )

    parser.add_argument("--cli", action="store_true", help="Запустить в консольном режиме (без GUI)")
    parser.add_argument("--start", action="store_true", help="Запустить DNS-сервер")
    parser.add_argument("--daemon", action="store_true", help="Запустить как фоновый сервис")
    parser.add_argument("--list", action="store_true", help="Показать текущую конфигурацию")
    parser.add_argument("--add-domain", nargs="+", metavar="DOMAIN", help="Добавить домен(ы) в маршрутизацию")
    parser.add_argument("--remove-domain", nargs="+", metavar="DOMAIN", help="Удалить домен(ы) из маршрутизации")
    parser.add_argument("--add-process", nargs="+", metavar="PROCESS", help="Добавить процесс(ы): домены этих приложений пойдут через xbox-dns")
    parser.add_argument("--remove-process", nargs="+", metavar="PROCESS", help="Удалить процесс(ы) из списка маршрутизации по приложениям")

    args = parser.parse_args()

    if (
        args.cli
        or args.start
        or args.list
        or args.add_domain
        or args.remove_domain
        or args.add_process
        or args.remove_process
    ):
        run_cli(args)
    else:
        run_gui()


if __name__ == "__main__":
    main()
