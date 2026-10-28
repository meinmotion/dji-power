"""AsyncBleHub — de BLE-databron als pure asyncio-component (geen threads, geen bleak-import).

De verbinding wordt niet hier opgebouwd maar aangereikt als `connect`: een coroutine-functie
die een *verbonden* bleak-achtige client teruggeeft (write_gatt_char/start_notify/disconnect/
is_connected). Zo kan Home Assistant zijn eigen Bluetooth-stack (adapters, ESPHome-proxies,
bleak-retry-connector) gebruiken, en het standalone dashboard een gewone BleakClient.

    hub = AsyncBleHub(connect, pair_key, sn)
    task = asyncio.create_task(hub.run())        # houdt de verbinding open + reconnect
    hub.subscribe(callback)                      # callback(state_dict) bij elke push
    await hub.set_light("on"); await hub.set_port(2, 1, False)
    await hub.stop()

De state-vorm is identiek aan DjiPowerHub (genormaliseerd: battery_pct, light_on, port_<t>_<s>…),
zodat dezelfde coordinator/entiteiten op beide bronnen draaien.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from . import ble_protocol as proto
from . import ble_state, model

_LOGGER = logging.getLogger(__name__)

ICONS = {2: "mdi:power-socket-eu", 3: "mdi:usb-port", 4: "mdi:usb-c-port", 5: "mdi:current-dc"}


def to_dashboard_state(st: dict) -> dict:
    """ble_state.parse_state -> de genormaliseerde state-keys van het dashboard."""
    out = {}
    lamp = st.get("lamp")
    if lamp:
        out["light_pct"] = lamp.get("pwm_v")
        out["light_on"] = "on" if (lamp["on"] or lamp["sos"]) else "off"
        out["light_fx"] = "SOS" if lamp["sos"] else "normaal"
    for p in st.get("ports", []):
        out[model.port_key(p["group"], p["index"])] = "on" if p["on"] else "off"
    return out


class AsyncBleHub:
    def __init__(self, connect, pair_key: str, sn: str | None = None, *,
                 on_connect_change=None, reconnect_delay: float = 3.0,
                 max_reconnect_delay: float = 30.0):
        self._connect = connect
        self._pair_key = pair_key
        self.sn = sn or "dji_power_ble"       # voor HA unique_ids
        self.on_connect_change = on_connect_change
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay
        self._listeners = []
        self._client = None
        self._write_c = None
        # State wordt op de loop-thread geschreven maar mag vanuit andere threads gelezen
        # worden (het webdashboard); vandaar het slot.
        self._lock = threading.Lock()
        self._osd: dict = {}
        self._state: dict = {}
        self._lamp: dict = {}             # laatste parse_lamp (ruw)
        self._interfaces: list = []       # laatste parse_interfaces (per-poort watt)
        self._ports: list[dict] = []      # laatste parse_state-poorten (voor SET + ruw)
        self._connected = False
        self._ts = 0.0
        self._stopping = False

    # ---- lezen ----
    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def state(self) -> dict:
        """Genormaliseerde state (osd + lamp/poort), zoals dji_power.hub.state."""
        with self._lock:
            out = dict(self._osd)
            out.update(self._state)
            return out

    def snapshot(self) -> dict:
        with self._lock:
            return {"connected": self._connected, "osd": dict(self._osd),
                    "state": dict(self._state), "ts": self._ts,
                    "lamp": dict(self._lamp),
                    "ports": [dict(p) for p in self._ports],
                    "interfaces": self._interfaces}

    def subscribe(self, callback):
        """Roep callback(state) aan bij elke push. Retour: unsubscribe-fn."""
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    def discover_ports(self):
        """(ptype, seq, naam, icon) per poort, zoals de HA-switch verwacht."""
        with self._lock:
            ports = list(self._ports)
        return [(p["group"], p["index"], p.get("name") or f"{p['group']}/{p['index']}",
                 ICONS.get(p["group"], "mdi:power-plug")) for p in ports]

    # ---- besturen ----
    async def set_light(self, mode: str):
        return await self.set_lamp_mode(str(mode).lower())

    async def set_light_brightness(self, pct: int):
        return await self.set_lamp_mode("on", brightness=pct)

    async def set_lamp(self, on: bool):
        return await self.set_lamp_mode("on" if on else "off")

    async def set_lamp_mode(self, mode: str, brightness: int | None = None):
        """mode ∈ {off,on,sos}. brightness (10-100) zet pwm_v (impliceert aan)."""
        res = await self._write_action(proto.build_lamp_payload(mode, brightness))
        st = proto.LAMP_STATE[mode]
        with self._lock:                      # optimistisch, tot de volgende push
            self._state["light_on"] = "on" if st in (2, 3) else "off"
            self._state["light_fx"] = "SOS" if st == 3 else "normaal"
            self._lamp["state"] = st
            self._lamp["on"] = st in (2, 3)
            self._lamp["sos"] = st == 3
            if brightness is not None:
                self._lamp["pwm_v"] = max(10, min(100, int(brightness)))
                self._state["light_pct"] = self._lamp["pwm_v"]
            self._ts = time.time()
        return res

    async def set_port(self, group: int, index: int, on: bool):
        with self._lock:
            states = {(p["group"], p["index"]): p["state"] for p in self._ports}
        if (group, index) not in states:
            raise RuntimeError("onbekende poort %d/%d" % (group, index))
        states[(group, index)] = 1 if on else 2   # een SET stuurt altijd alle poorten mee
        res = await self._write_action(proto.build_port_set(states))
        with self._lock:
            for p in self._ports:
                if (p["group"], p["index"]) == (group, index):
                    p["state"] = 1 if on else 2
                    p["on"] = on
            self._state[model.port_key(group, index)] = "on" if on else "off"
            self._ts = time.time()
        return res

    async def _write_action(self, payload: bytes):
        if not (self._client and self._client.is_connected):
            raise RuntimeError("niet verbonden")
        f = proto.request_frame(proto.CMD_ACTION, payload, proto.SEQ_ACTION)
        await self._client.write_gatt_char(self._write_c, f.build(), response=True)
        return True

    # ---- levenscyclus ----
    def request_stop(self):
        """Thread-veilig: de run()-lus eindigt binnen ~1s en koppelt los."""
        self._stopping = True

    async def stop(self):
        self._stopping = True
        client = self._client
        if client is not None:
            await self._disconnect(client)

    async def run(self):
        """Houd de verbinding open (handshake + subscribe) met reconnect-backoff."""
        self._stopping = False
        delay = self._reconnect_delay
        while not self._stopping:
            try:
                connected_ok = await self._session()
                if connected_ok:
                    delay = self._reconnect_delay
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.debug("BLE-sessie beëindigd", exc_info=True)
            self._set_connected(False)
            if not self._stopping:
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._max_reconnect_delay)

    def _set_connected(self, value: bool):
        with self._lock:
            changed = self._connected != value
            self._connected = value
        if changed and self.on_connect_change:
            try:
                self.on_connect_change(value)
            except Exception:  # noqa: BLE001
                _LOGGER.debug("on_connect_change faalde", exc_info=True)

    @staticmethod
    async def _disconnect(client):
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("disconnect faalde", exc_info=True)

    def _ingest(self, fr):
        if fr.cmd_id == proto.CMD_INFO:
            # Device-info (firmware). Bewust géén listener-aanroep: dit frame bevat geen
            # accu/poorten, dus het mag niet als "eerste data" tellen. De waarden gaan mee
            # met de eerstvolgende telemetrie-push.
            info = ble_state.parse_info(fr.payload)
            if info:
                with self._lock:
                    self._state.update(info)
            return
        # elke push (0x60-state of 0x61-telemetrie) bijwerken in de snapshot
        if fr.cmd_id in (proto.CMD_STATE, proto.CMD_PUSH) and len(fr.payload) > 40:
            osd = ble_state.parse_osd(fr.payload)
            st = ble_state.parse_state(fr.payload)
            ifaces = ble_state.parse_interfaces(fr.payload)
            with self._lock:
                if osd:
                    self._osd.update(osd)
                if ifaces:
                    self._interfaces = ifaces
                if st.get("ports"):
                    self._ports = st["ports"]
                if st.get("lamp"):
                    self._lamp = st["lamp"]
                self._state.update(to_dashboard_state(st))
                self._ts = time.time()
                snap = dict(self._osd)
                snap.update(self._state)
            for cb in list(self._listeners):
                try:
                    cb(snap)
                except Exception:  # noqa: BLE001
                    _LOGGER.debug("BLE-listener faalde", exc_info=True)

    async def _session(self) -> bool:
        """Eén verbindingssessie. Retour: True als de handshake slaagde."""
        c = await self._connect()
        self._client = c
        try:
            wc, ok = await proto.connect_and_auth(c, self._ingest, self._pair_key)
            if not ok:
                return False
            self._write_c = wc
            self._set_connected(True)
            # abonneer (0x60) zodat het device begint te pushen
            f = proto.request_frame(proto.CMD_STATE, proto.SUBSCRIBE_PAYLOAD, proto.SEQ_SUBSCRIBE)

            async def subscribe():
                await c.write_gatt_char(wc, f.build(), response=True)

            await subscribe()
            tick = 0
            while not self._stopping and c.is_connected:
                await asyncio.sleep(1)
                tick += 1
                if tick % 10 == 0:            # ~elke 10s state (lamp/poort) verversen
                    try:
                        await subscribe()
                    except Exception:  # noqa: BLE001
                        break
            return True
        finally:
            self._client = None
            await self._disconnect(c)
