"""
Тесты модуля автозапуска. На не-Windows проверяем graceful-degradation;
логику записи в реестр проверяем через мок winreg.
"""
import sys
import types

import autostart


def test_graceful_on_non_windows(monkeypatch):
    monkeypatch.setattr(autostart, "IS_WINDOWS", False)
    assert autostart.is_supported() is False
    assert autostart.is_enabled() is False
    ok, _ = autostart.enable()
    assert ok is False
    ok2, _ = autostart.disable()
    assert ok2 is False


def test_start_command_quotes_path():
    cmd = autostart._start_command()
    assert cmd.startswith('"') and cmd.endswith('"')
    assert "start.bat" in cmd


def _install_fake_winreg(monkeypatch, store):
    """Подсовывает фейковый модуль winreg, имитирующий HKCU\\...\\Run."""
    fake = types.ModuleType("winreg")
    fake.HKEY_CURRENT_USER = 1
    fake.KEY_READ = 1
    fake.KEY_WRITE = 2
    fake.REG_SZ = 1

    class FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def CreateKey(root, path):
        return FakeKey()

    def OpenKey(root, path, reserved, access):
        return FakeKey()

    def SetValueEx(key, name, reserved, typ, value):
        store[name] = value

    def QueryValueEx(key, name):
        if name not in store:
            raise FileNotFoundError(name)
        return store[name], fake.REG_SZ

    def DeleteValue(key, name):
        if name not in store:
            raise FileNotFoundError(name)
        del store[name]

    fake.CreateKey = CreateKey
    fake.OpenKey = OpenKey
    fake.SetValueEx = SetValueEx
    fake.QueryValueEx = QueryValueEx
    fake.DeleteValue = DeleteValue

    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(autostart, "IS_WINDOWS", True)
    return store


def test_enable_then_enabled_then_disable(monkeypatch):
    store = _install_fake_winreg(monkeypatch, {})

    assert autostart.is_enabled() is False        # пусто
    ok, _ = autostart.enable()
    assert ok is True
    assert "NetDocker" in store                    # значение записано
    assert autostart.is_enabled() is True

    ok2, _ = autostart.disable()
    assert ok2 is True
    assert "NetDocker" not in store
    assert autostart.is_enabled() is False


def test_disable_when_absent_is_ok(monkeypatch):
    _install_fake_winreg(monkeypatch, {})
    ok, _ = autostart.disable()       # значения нет — не ошибка
    assert ok is True


def test_set_enabled_dispatch(monkeypatch):
    store = _install_fake_winreg(monkeypatch, {})
    autostart.set_enabled(True)
    assert "NetDocker" in store
    autostart.set_enabled(False)
    assert "NetDocker" not in store
