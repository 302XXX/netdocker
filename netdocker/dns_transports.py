"""
NetDocker — дополнительные DNS-транспорты: DoT и DoQ
====================================================

Здесь живут низкоуровневые функции запроса к upstream по защищённым каналам:

  • DoT (DNS-over-TLS, RFC 7858) — TCP:853 внутри TLS. Использует только stdlib
    (socket + ssl), дополнительных зависимостей НЕ требует.

  • DoQ (DNS-over-QUIC, RFC 9250) — DNS поверх QUIC, UDP:853. Требует пакет
    `aioquic`. Если он не установлен — функция честно бросает понятную ошибку,
    а вызывающий код делает fallback на другой транспорт.

Все функции принимают и возвращают dnslib.DNSRecord (как и остальные транспорты
в dns_server.py), чтобы единообразно встраиваться в стратегию опроса.

Wire-format:
  - DoT использует тот же формат, что DNS-over-TCP: 2 байта длины + сообщение.
  - DoQ (RFC 9250): на каждый запрос — отдельный bidirectional stream,
    payload тоже с 2-байтным префиксом длины; поле ID в DNS-сообщении ДОЛЖНО
    быть 0 (требование RFC 9250 §4.2.1).
"""

import logging
import socket
import ssl
import struct

from dnslib import DNSRecord

log = logging.getLogger("NetDocker.Transports")

DOT_PORT = 853
DOQ_PORT = 853

# ── флаг доступности DoQ (aioquic) — вычисляется лениво ──────────────────────
_DOQ_IMPORT_ERROR = None


def doq_available() -> bool:
    """Доступен ли DoQ (установлен ли aioquic)."""
    import importlib.util
    try:
        return importlib.util.find_spec("aioquic") is not None
    except Exception as exc:  # pragma: no cover - зависит от окружения
        global _DOQ_IMPORT_ERROR
        _DOQ_IMPORT_ERROR = str(exc)
        return False


def _recv_exact(sock, size: int) -> bytes:
    """Читает ровно size байт (для length-prefixed TCP/TLS потока)."""
    chunks = []
    remaining = size
    while remaining > 0:
        data = sock.recv(remaining)
        if not data:
            raise ConnectionError("Соединение закрыто до получения полного ответа")
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def _ip_family(server_ip: str) -> int:
    return socket.AF_INET6 if ":" in server_ip else socket.AF_INET


def _socket_address(server_ip: str, port: int):
    if _ip_family(server_ip) == socket.AF_INET6:
        return (server_ip, port, 0, 0)
    return (server_ip, port)


# ── DoT (DNS-over-TLS) ───────────────────────────────────────────────────────

def query_dot(server_ip: str, request, timeout: float = 5.0,
              port: int = DOT_PORT, server_hostname: str = None,
              verify: bool = True):
    """Отправляет DNS-запрос по DNS-over-TLS (RFC 7858).

    server_ip        — IP DoT-сервера.
    server_hostname  — имя для SNI/проверки сертификата (если задано —
                       сертификат сервера проверяется по нему).
    verify           — проверять ли сертификат (по умолчанию да).
    Возвращает dnslib.DNSRecord либо бросает исключение.
    """
    wire = request.pack()

    ctx = ssl.create_default_context()
    if not verify or not server_hostname:
        # Без hostname проверить сертификат по имени нельзя; чтобы DoT всё же
        # работал по «голому» IP, отключаем проверку (как делают многие
        # резолверы для bootstrap). Это всё равно шифрованный канал.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    family = _ip_family(server_ip)
    raw = socket.socket(family, socket.SOCK_STREAM)
    raw.settimeout(timeout)
    try:
        raw.connect(_socket_address(server_ip, port))
        with ctx.wrap_socket(raw, server_hostname=server_hostname or None) as tls:
            tls.sendall(struct.pack("!H", len(wire)) + wire)
            resp_len = struct.unpack("!H", _recv_exact(tls, 2))[0]
            data = _recv_exact(tls, resp_len)
        return DNSRecord.parse(data)
    finally:
        try:
            raw.close()
        except Exception:
            pass


# ── DoQ (DNS-over-QUIC) ──────────────────────────────────────────────────────

def query_doq(server_ip: str, request, timeout: float = 5.0,
              port: int = DOQ_PORT, server_hostname: str = None,
              verify: bool = True):
    """Отправляет DNS-запрос по DNS-over-QUIC (RFC 9250).

    Требует пакет `aioquic`. Если он не установлен — бросает RuntimeError
    с понятным сообщением (вызывающий код сделает fallback).
    """
    if not doq_available():
        raise RuntimeError(
            "DoQ недоступен: не установлен пакет 'aioquic' "
            "(pip install aioquic). Используйте DoT/DoH/UDP."
        )

    import asyncio
    return asyncio.run(
        _query_doq_async(server_ip, request, timeout, port, server_hostname, verify)
    )


async def _query_doq_async(server_ip, request, timeout, port,
                           server_hostname, verify):
    from aioquic.asyncio.client import connect
    from aioquic.quic.configuration import QuicConfiguration

    # RFC 9250: ID в DNS-сообщении должен быть 0.
    q = request.pack()
    # подменяем первые 2 байта (ID) на 0
    wire = b"\x00\x00" + q[2:]

    config = QuicConfiguration(
        alpn_protocols=["doq"],
        is_client=True,
    )
    if not verify:
        config.verify_mode = ssl.CERT_NONE
    if server_hostname:
        config.server_name = server_hostname

    import asyncio

    async def _do():
        async with connect(
            server_ip, port,
            configuration=config,
            wait_connected=True,
        ) as client:
            reader, writer = await client.create_stream()
            # length-prefixed payload
            writer.write(struct.pack("!H", len(wire)) + wire)
            writer.write_eof()
            try:
                data = await reader.read()
            except ConnectionError:
                data = b""
            if len(data) < 2:
                raise ConnectionError("Пустой DoQ-ответ")
            resp_len = struct.unpack("!H", data[:2])[0]
            payload = data[2:2 + resp_len]
            return DNSRecord.parse(payload)

    return await asyncio.wait_for(_do(), timeout=timeout)
