"""
NetDocker - DPI Engine (Локальный обход блокировок)
Реализует модификацию TCP-пакетов для обхода систем DPI.

Методы:
  - Фрагментация TLS ClientHello (разбиение пакета на части).
  - Мутация регистра (Case-flipping) в SNI.
  - Отправка фейковых пакетов для десинхронизации DPI.
"""

import threading
import logging
import socket
import time
from typing import Set, List

# Пытаемся импортировать pydivert. 
# Внимание: требует установленного WinDivert драйвера в системе.
try:
    import pydivert
except ImportError:
    pydivert = None

log = logging.getLogger("NetDocker.DPIEngine")

class DPIEngine:
    def __init__(self, engine_ref):
        self.engine = engine_ref  # Ссылка на главный объект NetDockerDNS
        self.running = False
        self._thread = None
        self._stop_event = threading.Event()
        
        # Кэш IP-адресов заблокированных доменов
        self.routed_ips: Set[str] = set()
        self._last_ips_update = 0

    def _update_routed_ips(self):
        """
        Обновляет список IP-адресов для всех доменов из списка маршрутизации.
        Нужно, чтобы DPI-движок знал, какие пакеты резать, а какие пропускать.
        """
        now = time.time()
        if now - self._last_ips_update < 300: # Обновляем раз в 5 минут
            return

        log.info("Обновление списка IP для DPI-фильтрации...")
        new_ips = set()
        domains = self.engine.config.get("routed_domains", [])
        
        for domain in domains:
            try:
                # Получаем все IP домена (IPv4)
                addr_info = socket.getaddrinfo(domain, None, socket.AF_INET)
                for item in addr_info:
                    new_ips.add(item[4][0])
            except Exception as e:
                log.debug(f"Не удалось резолвить {domain}: {e}")
        
        self.routed_ips = new_ips
        self._last_ips_update = now
        log.info(f"DPI-фильтр обновлен: {len(self.routed_ips)} адресов в списке.")

    def _is_routed(self, ip: str) -> bool:
        """Проверяет, должен ли пакет модифицироваться."""
        self._update_routed_ips()
        return ip in self.routed_ips

    def _mutate_sni(self, data: bytes) -> bytes:
        """
        Метод Case-flipping: меняет регистр букв в SNI.
        Ищет заголовок Host или SNI и меняет регистр.
        """
        # Упрощенная реализация: ищем строки, похожие на домены, и меняем регистр
        # В реальности нужно искать точно по смещению TLS Client Hello
        res = bytearray(data)
        for i in range(len(res) - 1):
            if 65 <= res[i] <= 90: # Upper
                res[i] = res[i] + 32
            elif 97 <= res[i] <= 122: # Lower
                res[i] = res[i] - 32
        return bytes(res)

    def _fragment_packet(self, packet):
        """
        Метод фрагментации (Split):
        Разбивает один TCP пакет на два маленьких.
        DPI часто не умеет склеивать их для анализа SNI.
        """
        payload = packet.payload
        if len(payload) < 5: # Слишком маленький пакет для фрагментации
            packet.send()
            return

        # Точка разреза: обычно 1-5 байт.
        split_pos = 2 
        
        # Первый пакет (фрагмент)
        packet1 = packet.copy()
        packet1.payload = payload[:split_pos]
        packet1.send()

        # Второй пакет (остаток)
        packet2 = packet.copy()
        packet2.payload = payload[split_pos:]
        # Корректируем Sequence Number для второго пакета
        packet2.tcp.seq += split_pos
        packet2.send()

    def _send_fake_packet(self, packet):
        """
        Метод фейковых пакетов (Fake):
        Отправляет пакет с малым TTL, который дойдет до DPI, но не до сервера.
        Этот пакет выглядит как начало TLS-соединения, но содержит мусор.
        """
        # Создаем фейковый пакет на основе оригинала
        fake = packet.copy()
        
        # Модифицируем payload, чтобы он выглядел как TLS, но был некорректным
        # 0x16 (Handshake) + 0x03 0x01 (TLS 1.0) + случайная длина + мусор
        fake_payload = bytearray([0x16, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00])
        fake_payload.extend(b"FAKE_TLS_DATA_TO_CONFUSE_DPI" * 2)
        fake.payload = bytes(fake_payload)
        
        # Устанавливаем маленький TTL, чтобы пакет умер на DPI (обычно 3-10)
        fake.ip.ttl = 4
        
        # Отправляем фейк
        fake.send()
        
        # Затем отправляем оригинал (возможно, с модификацией)
        packet.send()

    def _process_packet(self, packet):
        """Основная логика обработки каждого перехваченного пакета."""
        # 1. Проверяем, идет ли пакет на наш целевой IP
        if not self._is_routed(packet.dst_addr):
            return # Пропускаем пакет без изменений

        # 2. Проверяем, что это TCP порт 443 (HTTPS)
        if packet.dst_port != 443:
            return

        # 3. Детекция TLS Client Hello (первый байт 0x16 - Handshake)
        payload = packet.payload
        if len(payload) > 0 and payload[0] == 0x16:
            log.debug(f"Перехвачен TLS Client Hello для {packet.dst_addr}")
            
            # Применяем одну из стратегий в зависимости от режима.
            # В будущем можно добавить перебор стратегий.
            
            # По умолчанию пробуем комбинацию:
            # 1. Кейс-флиппинг SNI
            # 2. Фрагментация
            
            # Применяем Case-flipping к оригинальному payload
            mutated_payload = self._mutate_sni(payload)
            packet.payload = mutated_payload
            
            # Теперь либо фрагментируем, либо отправляем фейк + оригинал
            # Для простоты сейчас используем фрагментацию как основную
            self._fragment_packet(packet)
            return # Важно: _fragment_packet уже вызвал .send()

        # Возвращаем пакет в сеть, если он не был модифицирован
        packet.send()

    def start(self, mode: str):
        """
        Запуск движка. 
        mode: 'combo' (🔵) или 'zapret' (🔴)
        """
        if not pydivert:
            log.error("Библиотека pydivert не установлена. DPI-движок не может работать.")
            return False

        if self.running:
            return True

        self.running = True
        self._stop_event.clear()
        
        # Фильтр WinDivert: перехватываем только исходящий TCP трафик на 443 порт.
        # Это минимизирует нагрузку на систему.
        filter_str = "outbound and tcp.DstPort == 443"
        
        def worker():
            try:
                with pydivert.WinDivert(filter_str) as w:
                    log.info(f"DPI-движок запущен в режиме {mode}. Ожидание пакетов...")
                    while not self._stop_event.is_set():
                        # Ждем пакет с таймаутом, чтобы проверять stop_event
                        try:
                            packet = w.recv(timeout=1.0)
                            self._process_packet(packet)
                        except pydivert.exceptions.Timeout:
                            continue
            except Exception as e:
                log.error(f"Критическая ошибка DPI-движка: {e}")
                self.running = False

        self._thread = threading.Thread(target=worker, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Остановка перехвата пакетов."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.running = False
        log.info("DPI-движок остановлен.")
