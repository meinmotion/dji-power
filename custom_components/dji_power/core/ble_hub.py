"""Persistente BLE-verbinding met de DJI Power, met een thread-veilige (synchrone) API.

Dunne wrapper om AsyncBleHub voor consumers zonder eigen asyncio-loop (het webdashboard):
draait een eigen loop in een achtergrond-thread en gebruikt een gewone BleakClient. De
protocol-/state-logica woont in ble_async.py; Home Assistant gebruikt AsyncBleHub direct.

    hub = BleHub(address, pair_key); hub.start()
    hub.snapshot()                      -> {'connected','osd','state','ts'}
    hub.set_lamp(True/False)            -> stuurt een 0x63-SET
    hub.set_port(group, index, True/False)

De OSD/state-vorm is identiek aan dji_power.normalize (battery_pct, temp_c, …,
light_on, port_<t>_<s>), zodat het bestaande dashboard ongewijzigd rendert.

Importeert bleak: importeer deze module dus alleen als de BLE-route gebruikt wordt.
"""
from __future__ import annotations

import asyncio
import threading

from bleak import BleakClient

from .ble_async import AsyncBleHub, to_dashboard_state

_to_dashboard_state = to_dashboard_state      # backwards-compat naam


class BleHub:
    def __init__(self, address: str, pair_key: str, sn: str | None = None):
        self.address = address
        self._core = AsyncBleHub(self._connect, pair_key, sn)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread = None

    async def _connect(self):
        client = BleakClient(self.address, timeout=20)
        await client.connect()
        return client

    # ---- levenscyclus ----
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._core.request_stop()

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._core.run())

    def _submit(self, coro):
        if self._loop is None:
            coro.close()
            raise RuntimeError("hub niet gestart")
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=10)

    # ---- lezen (DjiPowerHub-compatibel, voor dashboard en coordinator) ----
    @property
    def sn(self) -> str:
        return self._core.sn

    @property
    def connected(self) -> bool:
        return self._core.connected

    @property
    def state(self) -> dict:
        return self._core.state

    def snapshot(self) -> dict:
        return self._core.snapshot()

    def subscribe(self, callback):
        return self._core.subscribe(callback)

    def prime_from_settings(self):
        """Geen aparte REST-prime nodig; de eerste subscribe-response vult de state."""
        return self.state

    def discover_ports(self):
        return self._core.discover_ports()

    # ---- besturen ----
    def set_light(self, mode: str):
        return self._submit(self._core.set_light(mode))

    def set_light_brightness(self, pct: int):
        return self._submit(self._core.set_light_brightness(pct))

    def set_lamp(self, on: bool):
        return self._submit(self._core.set_lamp(on))

    def set_lamp_mode(self, mode: str, brightness: int | None = None):
        return self._submit(self._core.set_lamp_mode(mode, brightness))

    def set_lamp_brightness(self, pct: int):
        return self.set_light_brightness(pct)

    def set_port(self, group: int, index: int, on: bool):
        return self._submit(self._core.set_port(group, index, on))
