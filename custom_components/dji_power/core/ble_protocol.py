"""DJI Power BLE-protocol (dy303): GATT-profielen, constanten, payload-bouwers en handshake.

Vastgelegd uit captures/btsnoop_ble_dy303.log, zie PROTOCOL_BLE.md. Alles is plaintext
DUML V1 (zie duml.py); geen crypto nodig. Deze module is framework-agnostisch en importeert
bleak niet zelf: de handshake krijgt een al verbonden client aangereikt.
"""
from __future__ import annotations

import asyncio
import logging

from . import duml

_LOGGER = logging.getLogger(__name__)


def uuid16(short: str) -> str:
    """16-bits UUID -> volledige Bluetooth-base-UUID."""
    return "0000%s-0000-1000-8000-00805f9b34fb" % short


# --- GATT-profielen (pp.txt:16577-16582). De app kent twee BLE-UART-profielen;
#     elk cluster is {service, notify, write}. Welke actief is verschilt per device:
#     de Power 1000 Mini (dy303) exposeert het a002-profiel, niet fff0. ---
PROFILES = [
    # (service, notify, write, write_without_response)
    # dy303 (Power 1000 Mini). c303 = write-without-response, c304 = write-with-response.
    (uuid16("a002"), uuid16("c305"), uuid16("c304"), False),
    (uuid16("fff0"), uuid16("fff4"), uuid16("fff5"), True),
]
A002_INDICATE = uuid16("c306")

# --- Power-protocol (dy303), vastgelegd uit captures/btsnoop_ble_dy303.log ---
POWER_CMD_SET = 0x5a          # alle Power-berichten
POWER_ADDR = 0xab             # receiver-adres van de Power
CMD_CONNECT = 0x6a            # StartConnect + ConnectDevice
CMD_STATE = 0x60              # subscribe/get
CMD_PUSH = 0x61               # telemetrie-push (dev->app)
CMD_INFO = 0x62               # device-info-snapshot
CMD_ACTION = 0x63             # SET/action
CMD_HMS = 0x66                # health/status
# ConnectDeviceCmdTypeEnum
CONNECT_SUB = 0x01            # "connectDevice"

# Seq-nummers zoals de app ze gebruikt (aparte reeksen per stroom).
SEQ_START_CONNECT = 10001
SEQ_CONNECT_DEVICE = 10002
SEQ_SUBSCRIBE = 10008
SEQ_ACTION = 10014


# 0x63-SET-payload voor de lamp, letterlijk uit captures/btsnoop_ble_dy303.log (#894),
# alleen de state-byte is parametrisch. Structuur:
#   [16B envelope-header] 0e100e00 <14B component-id> 1b100400 <state> 64 0a 64
# key 0x1b = lamp; state 0x02=aan, 0x01=uit; 0x64=helderheid(100%).
LAMP_SET_TEMPLATE = bytes.fromhex(
    "00001000aedbcc1fa0010000000000000e100e000c00316330306566666666663066"
    "1b10040002640a64")
# state-byte staat direct na de TLV-kop 1b100400 (key 0x1b, type 0x10, len 4).
LAMP_TLV = bytes.fromhex("1b100400")
LAMP_STATE_OFFSET = LAMP_SET_TEMPLATE.index(LAMP_TLV) + len(LAMP_TLV)
LAMP_STATE = {"off": 0x01, "on": 0x02, "sos": 0x03}   # == cloud-enum lamp-state


def build_lamp_payload(state: str, brightness: int | None = None) -> bytes:
    """0x63-lamp-SET. state ∈ {off,on,sos}; brightness (10-100) zet pwm_v (byte na state)."""
    b = bytearray(LAMP_SET_TEMPLATE)
    b[LAMP_STATE_OFFSET] = LAMP_STATE[state]
    if brightness is not None:
        b[LAMP_STATE_OFFSET + 1] = max(10, min(100, int(brightness)))   # pwm_v
    return bytes(b)


# Subscribe-payload (0x60) letterlijk uit de capture: de key-lijst waarop de app
# abonneert. De device-response is de volledige property-state.
SUBSCRIBE_PAYLOAD = bytes.fromhex(
    "0000100210031005100610071008100910"
    "0a100b100c100d100e10151016101810191"
    "01b101c101d101e102010211022102310241025102610271028 10".replace(" ", ""))
# Component-id-entry (0e) uit de capture; constant voor dit device.
PORT_COMPONENT = bytes.fromhex("0e100e000c00316330306566666666663066")
# Poort-SET envelope-header (16B); de timestamp wordt niet gevalideerd (lamp werkte
# met een stale waarde), dus we hergebruiken een capture-waarde.
PORT_HEADER = bytes.fromhex("00001000aedbcc1fa001000000000000")
PORT_ORDER = [(2, 1), (4, 1), (4, 2), (3, 1), (3, 2), (5, 1)]


def build_port_set(states: dict) -> bytes:
    """Bouw een 0x63-poort-SET. states = {(group,index): state 1=aan/2=uit} voor ALLE poorten."""
    inner = b""
    for g, i in PORT_ORDER:
        st = states[(g, i)]
        inner += bytes([0x0d, 0x00, 0x03, 0x00, g, i, st])
    container = bytes([0x0d, 0x10, len(inner) & 0xFF, (len(inner) >> 8) & 0xFF]) + inner
    return PORT_HEADER + container + PORT_COMPONENT


def request_frame(cmd_id: int, payload: bytes, seq: int) -> duml.Frame:
    """App->Power request-frame (ack-before, plaintext) voor cmd_set 0x5a."""
    req = duml.cmd_type(duml.PKT_REQUEST, duml.ACK_BEFORE, duml.ENC_NONE)
    return duml.Frame(cmd_set=POWER_CMD_SET, cmd_id=cmd_id, payload=payload,
                      sender=duml.ADDR_APP, receiver=POWER_ADDR, seq=seq, cmd_type=req)


async def connect_and_auth(c, on_frame, pair_key: str, log=None):
    """Gedeelde handshake: subscribe c305/c306, StartConnect, ConnectDevice(nonce).

    `c` is een verbonden bleak-client, `pair_key` de 32-teken hexstring uit
    `pair_info.pair_key` van de cloud-apparatenlijst. on_frame(fr) krijgt elk binnenkomend
    frame; `log` ontvangt voortgangsregels (default: logging). Retourneert (write_char, ok).
    """
    log = log or _LOGGER.info
    write_c = PROFILES[0][2]
    notify_c, indicate_c = PROFILES[0][1], A002_INDICATE
    reasm = duml.Reassembler()
    state = {"nonce": None, "auth": None}

    def cb(ch, data):
        for fr in reasm.feed(bytes(data)):
            if fr.cmd_id == CMD_CONNECT and fr.seq == SEQ_START_CONNECT and len(fr.payload) >= 5:
                state["nonce"] = fr.payload[1:5]
            if fr.cmd_id == CMD_CONNECT and fr.seq == SEQ_CONNECT_DEVICE and len(fr.payload) >= 1:
                state["auth"] = fr.payload[0]
            on_frame(fr)

    for ch in (notify_c, indicate_c):
        try:
            await c.start_notify(ch, cb)
        except Exception as e:  # noqa: BLE001
            log("notify-fout %s: %s" % (ch, e))

    f1 = request_frame(CMD_CONNECT, b"\x00", SEQ_START_CONNECT)
    await c.write_gatt_char(write_c, f1.build(), response=True)
    for _ in range(20):
        if state["nonce"] is not None:
            break
        await asyncio.sleep(0.1)
    if state["nonce"] is None:
        log("geen nonce; handshake mislukt")
        return write_c, False
    payload = bytes([CONNECT_SUB]) + state["nonce"] + pair_key.encode("ascii") + b"\x00"
    f2 = request_frame(CMD_CONNECT, payload, SEQ_CONNECT_DEVICE)
    await c.write_gatt_char(write_c, f2.build(), response=True)
    for _ in range(20):
        if state["auth"] is not None:
            break
        await asyncio.sleep(0.1)
    ok = state["auth"] == 0x00
    log("handshake: " + ("OK (status 0x00)" if ok else "MISLUKT status=%s" % state["auth"]))
    return write_c, ok
