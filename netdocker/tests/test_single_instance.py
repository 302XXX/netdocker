"""
Тесты защиты от запуска второй копии (SingleInstance).
"""
import os
import tempfile

from single_instance import SingleInstance


def _lock_name():
    # уникальное имя на каждый тест, чтобы тесты не мешали друг другу
    return f"netdocker_test_{os.getpid()}_{id(object())}.lock"


def test_first_instance_acquires():
    name = _lock_name()
    g = SingleInstance(name)
    try:
        assert g.already_running() is False
    finally:
        g.release()


def test_second_instance_detected():
    name = _lock_name()
    g1 = SingleInstance(name)
    g2 = SingleInstance(name)
    try:
        assert g1.already_running() is False
        assert g2.already_running() is True   # вторая копия видит, что уже занято
    finally:
        g1.release()
        g2.release()


def test_release_allows_new_instance():
    name = _lock_name()
    g1 = SingleInstance(name)
    assert g1.already_running() is False
    g1.release()
    g2 = SingleInstance(name)
    try:
        assert g2.already_running() is False   # после release снова можно
    finally:
        g2.release()


def test_context_manager_releases():
    name = _lock_name()
    with SingleInstance(name) as g:
        assert g.already_running() is False
    # после выхода из with блокировка снята
    g2 = SingleInstance(name)
    try:
        assert g2.already_running() is False
    finally:
        g2.release()


def test_lock_file_path_in_temp():
    name = _lock_name()
    g = SingleInstance(name)
    try:
        assert g.lock_path.startswith(tempfile.gettempdir())
    finally:
        g.release()


def test_show_signal_roundtrip():
    from single_instance import request_show_existing, consume_show_request
    # на всякий случай очищаем возможный остаток
    consume_show_request()
    assert consume_show_request() is False    # пусто
    request_show_existing()
    assert consume_show_request() is True      # сигнал получен
    assert consume_show_request() is False     # и сброшен (одноразовый)
