"""Enums en afgeleide device-modellen voor de DJI Power-lijn.

Alle enum-waarheid staat hier (voorheen los verspreid over dji_control.py,
dji_ha.py en de JS in dji_web.py). Geldt voor de hele Power-lijn
(1000, 1000 Mini, 1000 V/V2, 2000, 2000 Mini).
"""
from collections import Counter

# light-state-enum (Mya, uit Blutter): 1=uit, 2=aan (helderheid=pwm_v 10-100%), 3=SOS
LIGHT_OFF, LIGHT_ON, LIGHT_SOS = 1, 2, 3
LIGHT_MODES = {
    "off": LIGHT_OFF, "uit": LIGHT_OFF,
    "on": LIGHT_ON, "aan": LIGHT_ON, "constant": LIGHT_ON,
    "sos": LIGHT_SOS,
}

# power_sw-enum (Lsa, uit Blutter): 1=aan (open), 2=uit (close) — géén 0/1!
PORT_ON, PORT_OFF = 1, 2

# poort-type -> naam/icon (voor de hele Power-lijn)
PORT_TYPE_NAMES = {1: "Hoofd/DC", 2: "AC-uitgang", 3: "USB-A", 4: "USB-C",
                   5: "SDC", 6: "DC/Car", 7: "XT60"}
PORT_TYPE_ICONS = {1: "mdi:power-plug", 2: "mdi:power-socket-eu", 3: "mdi:usb",
                   4: "mdi:usb-port", 5: "mdi:car-battery", 6: "mdi:car", 7: "mdi:power-plug"}


def discover_ports(power_sw_data):
    """Bouw de poortenlijst dynamisch uit power_sw.data (model-onafhankelijk).

    power_sw_data: de lijst uit settings["power_sw"]["data"] (elk item heeft type/seq).
    Retour: lijst van (type, seq, naam, icon). Bij meerdere poorten van hetzelfde
    type krijgt de naam een volgnummer (bv. "USB-C 1"/"USB-C 2").
    """
    cnt = Counter(s["type"] for s in power_sw_data)
    out = []
    for s in power_sw_data:
        t, seq = s["type"], s["seq"]
        base = PORT_TYPE_NAMES.get(t, f"Poort {t}")
        name = f"{base} {seq}" if cnt[t] > 1 else base
        out.append((t, seq, name, PORT_TYPE_ICONS.get(t, "mdi:power-socket-eu")))
    return out


def port_key(ptype, seq):
    """Stabiele sleutel voor een poort in de genormaliseerde state ('port_<t>_<seq>')."""
    return f"port_{ptype}_{seq}"
