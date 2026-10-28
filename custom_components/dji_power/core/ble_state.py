"""Decodeer de DJI Power BLE-state (property-TLV) uit een 0x60/0x61-payload.

Het BLE-protocol (cmd_set 0x5a) draagt de device-state als property-TLV, niet als de
JSON van de cloud-REST. Zie PROTOCOL_BLE.md. Geverifieerd tegen de cloud-grondwaarheid
(`dji_control.py state`): lamp-state + pwm en de zes poortstanden komen exact overeen.

Structuur van een property-entry: [key:1B] [type:1B] [len:2B LE] [value].
- type 0x10 met een geneste TLV = container (o.a. de poort-lijst, key 0x0d).
- De poort-lijst bevat entries `14 1003 00 <groep> <index> <state>` in de READ-state
  (in een 0x63-SET-write zijn de inner-keys 0x0d i.p.v. 0x14).
- Lamp = entry `1b 1004 00 <state> <pwm_v> <pwm_low> <x>`.

Enums (== cloud): lamp state 1=uit/2=aan/3=SOS; poort state 1=aan/2=uit.
"""
from __future__ import annotations

import re

# Poort-labels (groep,index) -> naam, uit de cloud-normalisatie.
PORT_NAMES = {
    (2, 1): "AC-uitgang",
    (4, 1): "USB-C-1", (4, 2): "USB-C-2",
    (3, 1): "USB-A-1", (3, 2): "USB-A-2",
    (5, 1): "SDC/DC",
}


def parse_ports(payload: bytes) -> list[dict]:
    """Haal de poortstanden uit een state-payload via de 0d102a-container.

    Retour: [{'group','index','on','name'}], in wire-volgorde.
    """
    i = payload.find(bytes.fromhex("0d102a00"))
    if i < 0:
        return []
    body = payload[i + 4:i + 4 + 0x2a]      # 42-byte container
    ports = []
    o = 0
    while o + 7 <= len(body):
        key = body[o]                        # 0x14 (read) of 0x0d (write)
        # entry = key, type(00), len(0300), group, index, state
        length = body[o + 2] | (body[o + 3] << 8)
        g, idx, st = body[o + 4], body[o + 5], body[o + 6]
        ports.append({"group": g, "index": idx, "on": st == 1,
                      "state": st, "name": PORT_NAMES.get((g, idx), f"{g}/{idx}")})
        o += 4 + length
    return ports


def parse_lamp(payload: bytes) -> dict | None:
    """Haal de lampstatus uit een state-payload via de 1b1004-entry."""
    i = payload.find(bytes.fromhex("1b1004"))
    if i < 0:
        return None
    v = payload[i + 4:i + 8]                 # 4-byte value
    if len(v) < 4:
        return None
    return {"state": v[0], "on": v[0] == 2, "sos": v[0] == 3,
            "pwm_v": v[1], "pwm_low": v[2]}


def parse_state(payload: bytes) -> dict:
    return {"lamp": parse_lamp(payload), "ports": parse_ports(payload)}


def _find_block(payload: bytes, key: int) -> bytes | None:
    """Zoek een property-blok in een push/state-payload: [key][type][len:2LE][value].

    De payload begint met een 16-byte envelope-header; daarna volgen de blokken.
    """
    o = 16
    while o + 4 <= len(payload):
        k = payload[o]; ln = payload[o + 2] | (payload[o + 3] << 8)
        if k == key:
            return payload[o + 4:o + 4 + ln]
        o += 4 + ln
    return None


def _le16(b: bytes, off: int) -> int | None:
    return (b[off] | (b[off + 1] << 8)) if off + 2 <= len(b) else None


def parse_osd(payload: bytes) -> dict:
    """Decodeer de numerieke telemetrie uit een 0x61-push (of 0x60-state).

    Retourneert dezelfde vorm als dji_power.normalize.normalize_osd:
    {battery_pct, temp_c, remain_min, output_w, input_w, charging}.
    Geverifieerd tegen de cloud-OSD: charge_pct/100, temp/100, output/input in watt.

    Blok 0x20 (accu): charge_pct:u16, remain_time:u16, time_type:u8, prim_charge_pct:u16,
    prim_remain_time:u16, temp:u16, temp_t:u8.
    Blok 0x30 (vermogen): output:u16, input:u16, ... (poort-interfaces).
    """
    out = {}
    bat = _find_block(payload, 0x20)
    if bat:
        pct = _le16(bat, 0)
        if pct is not None:
            out["battery_pct"] = round(pct / 100)
        rem = _le16(bat, 2)
        if rem is not None:
            out["remain_min"] = rem
        temp = _le16(bat, 9)
        if temp is not None:
            out["temp_c"] = round(temp / 100, 1)
    pw = _find_block(payload, 0x30)
    if pw:
        o = _le16(pw, 0); i = _le16(pw, 2)
        if o is not None:
            out["output_w"] = o
        if i is not None:
            out["input_w"] = i
    out["charging"] = "on" if out.get("input_w", 0) > 0 else "off"
    return out


def parse_interfaces(payload: bytes) -> list[dict]:
    """Per-poort watt uit blok 0x30. Retour: cloud-interfaces-vorm [{list:[{...}]}].

    Blok 0x30 draagt per VERBONDEN poort een leaf [seq:1][type:1][sw:1][out:u16][in:u16].
    Alleen actieve poorten verschijnen (net als de cloud-interfaces). Geverifieerd: de som
    van de per-poort output == de totale output in ~99% van de pushes (btsnoop_ble_dy303).
    """
    b = _find_block(payload, 0x30)
    if not b:
        return []
    ports = []
    seen = set()
    for j in range(4, len(b) - 6):
        seq, typ, sw = b[j], b[j + 1], b[j + 2]
        if seq in (1, 2) and typ in (2, 3, 5) and sw in (0, 1):
            o = b[j + 3] | (b[j + 4] << 8)
            i = b[j + 5] | (b[j + 6] << 8)
            if o < 5000 and i < 5000 and (o > 0 or i > 0) and (typ, seq) not in seen:
                seen.add((typ, seq))
                ports.append({"seq": seq, "type": typ, "sw": sw,
                              "output": o, "input": i})
    return [{"list": ports}] if ports else []


_VERSION_RE = re.compile(rb"\d{2}\.\d{2}\.\d{4}")


def parse_info(payload: bytes) -> dict:
    """Firmwareversies uit de 0x62 device-info-push.

    De push bevat twee versiestrings; de volgorde is dezelfde als in het cloud-settings-object
    (geverifieerd 2026-10-28): eerst firm_ver (hoofdfirmware), dan wireless_firm_ver.
    """
    found = [m.decode("ascii") for m in _VERSION_RE.findall(payload)]
    out = {}
    if len(found) >= 1:
        out["fw_version"] = found[0]
    if len(found) >= 2:
        out["wireless_fw_version"] = found[1]
    return out
