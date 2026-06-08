def is_domain_routed(domain: str, config: dict, process_tracker=None) -> bool:
    """Проверяет, нужно ли этот домен резолвить через xbox-dns.ru.

    Логика additive (домен маршрутизируется, если выполнено ЛЮБОЕ условие):
      1) route_all включён;
      2) домен (или его поддомен) есть в config["routed_domains"];
      3) NEW: домен недавно запрашивал процесс из config["routed_processes"]
         (определяется через process_tracker — см. process_dns_tracker.py).

    process_tracker=None по умолчанию → пункт 3 отключён, поведение полностью
    обратно совместимо (маршрутизация только по доменам).
    """
    if config.get("route_all"):
        return True

    domain = domain.rstrip('.').lower()

    # (2) по списку доменов
    for routed in config.get("routed_domains", []):
        routed = str(routed).rstrip('.').lower()
        if domain == routed or domain.endswith('.' + routed):
            return True

    # (3) по процессам (per-app routing)
    if process_tracker is not None:
        routed_processes = config.get("routed_processes", []) or []
        if routed_processes and process_tracker.domain_requested_by(domain, routed_processes):
            return True

    return False
