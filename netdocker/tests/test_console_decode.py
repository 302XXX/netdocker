"""
Тесты декодирования вывода консольных утилит Windows (netsh/powershell).

Регрессия на баг: на русской Windows вывод приходит в cp866, а при text=True
Python декодировал его как utf-8 → текст ошибки превращался в «кракозябры»
или падал с UnicodeDecodeError, из-за чего автопереключение DNS «молча»
не работало.
"""
import process_monitor as pm


def test_decodes_cp866_russian_error():
    """Русский текст ошибки из cp866 должен читаться корректно."""
    russian_error = "Ethernet: Не удался запрос. Доступ запрещён."
    raw = ("OK:\nERR:" + russian_error).encode("cp866")
    decoded = pm._decode_console(raw)
    assert russian_error in decoded
    assert "ERR:" in decoded


def test_old_utf8_path_would_break():
    """Подтверждаем, что наивное utf-8 декодирование как раз и ломалось."""
    raw = "ERR:Доступ запрещён".encode("cp866")
    try:
        raw.decode("utf-8")
        broke = False
    except UnicodeDecodeError:
        broke = True
    assert broke, "cp866-байты не должны валидно декодироваться как utf-8"


def test_ascii_output_unchanged():
    """Чистый ASCII-вывод (успех без ошибок) не должен пострадать."""
    assert pm._decode_console(b"OK:Ethernet,Wi-Fi") == "OK:Ethernet,Wi-Fi"


def test_handles_str_passthrough():
    """Если вдруг пришла уже строка — возвращаем как есть, без падения."""
    assert pm._decode_console("OK:Ethernet") == "OK:Ethernet"


def test_handles_none():
    """None не должен валить декодер."""
    assert pm._decode_console(None) == ""


def test_never_raises_on_garbage():
    """Любые байты декодируются без исключения (есть errors='replace')."""
    result = pm._decode_console(bytes(range(256)))
    assert isinstance(result, str)
