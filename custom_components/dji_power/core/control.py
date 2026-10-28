#!/usr/bin/env python3
"""Schone besturing van de DJI Power via de cloud-REST-API — GEEN emulator nodig.

Ontdekt via Blutter-decompilatie van libapp.so (de packer had de .dynsym gestript;
zie tools/fix_elf.py). De app stuurt bij elke wijziging het VOLLEDIGE settings-object
terug (read-modify-write):

    PUT /dy/app/api/v1/devices/<SN>/settings
    headers: x-member-token
    body: {"double_check": false, "param": <alle settings, met 1 veld gewijzigd>}

Een partieel param (bv. alleen {"light": ...}) geeft 121001 "parameter error";
alleen het complete object wordt geaccepteerd. De server antwoordt vaak met
121804 "Device response timeout", maar de wijziging wordt wél toegepast — daarom
verifiëren we via een GET.

Lamp-standen (enum Mya): 1=uit, 2=aan (helderheid = pwm_v, 10-100%), 3=SOS.

CLI:
  python -m dji_power.control light on|off|sos
  python -m dji_power.control light bri 50        # helderheid 10-100%
  python -m dji_power.control port <type> <seq> on|off   # bv. port 2 1 off = AC uit
  python -m dji_power.control set <pad> <waarde>          # generiek, bv:
      set charge_limit.chg_up 90     (laadlimiet 90%)
      set ac_hz_gear.gear 2          (AC-frequentie-gear)
      set display.temp_unit 2        (°C/°F)
  python -m dji_power.control state
"""
import sys
import copy
import time

from . import config
from .model import LIGHT_MODES, LIGHT_OFF, LIGHT_ON, PORT_ON, PORT_OFF, PORT_TYPE_NAMES
from .rest import RestClient


def _client(sn=None, token=None):
    return RestClient(token or config.default_token(), sn or config.default_sn())


def get_settings(sn=None, token=None, client=None):
    return (client or _client(sn, token)).get_settings()


def apply_change(mutate, sn=None, token=None, client=None, double_check=False, verify=True):
    """GET volledige settings -> mutate(param) -> PUT terug. Verifieert via GET.

    mutate: functie die het (deep-copied) settings-dict in-place aanpast.
    Retour: dict {code, message, applied(bool of None), settings(na)}.
    """
    cli = client or _client(sn, token)
    full = cli.get_settings()
    param = copy.deepcopy(full)
    mutate(param)
    resp = cli.put_settings(param, double_check=double_check)
    res = (resp or {}).get("result", {}) if isinstance(resp, dict) else {}
    out = {"code": res.get("code"), "message": res.get("message"), "applied": None, "settings": None}
    if verify:
        time.sleep(1.5)
        out["settings"] = cli.get_settings()
    return out


def set_light(mode, sn=None, token=None, client=None, verify=True):
    """mode: 'off'|'on'|'sos' (of True/False voor aan/uit)."""
    if isinstance(mode, bool):
        want = LIGHT_ON if mode else LIGHT_OFF
    else:
        want = LIGHT_MODES.get(str(mode).lower())
        if want is None:
            raise ValueError(f"onbekende lamp-mode: {mode}")

    def m(p):
        p["light"]["data"]["state"] = want
        if want == LIGHT_ON and p["light"]["data"].get("pwm_v", 0) < 10:
            p["light"]["data"]["pwm_v"] = 100   # niet 0% laten staan bij 'aan'

    out = apply_change(m, sn, token, client=client, verify=verify)
    if out["settings"] is not None:
        out["applied"] = out["settings"]["light"]["data"]["state"] == want
    return out


def set_port(ptype, seq, on, sn=None, token=None, client=None, verify=True):
    want = PORT_ON if on else PORT_OFF

    def m(p):
        for s in p["power_sw"]["data"]:
            if s["type"] == ptype and s["seq"] == seq:
                s["sw"] = want

    out = apply_change(m, sn, token, client=client, verify=verify)
    if out["settings"] is not None:
        cur = [s["sw"] for s in out["settings"]["power_sw"]["data"]
               if s["type"] == ptype and s["seq"] == seq]
        out["applied"] = bool(cur) and cur[0] == want
    return out


def set_light_brightness(pct, sn=None, token=None, client=None, verify=True):
    """Helderheid 10-100% (zet de lamp op 'aan'/constant). 0 => uit."""
    pct = int(pct)

    def m(p):
        if pct <= 0:
            p["light"]["data"]["state"] = LIGHT_OFF
        else:
            lo = p["light"]["data"].get("pwm_low", 10) or 10
            p["light"]["data"]["pwm_v"] = max(lo, min(100, pct))
            p["light"]["data"]["state"] = LIGHT_ON

    out = apply_change(m, sn, token, client=client, verify=verify)
    if out["settings"] is not None:
        d = out["settings"]["light"]["data"]
        out["applied"] = (d["state"] == LIGHT_OFF) if pct <= 0 else (d["state"] == LIGHT_ON)
    return out


def set_charge_limit(pct, sn=None, token=None, client=None, verify=True):
    """Laadlimiet % (charge_limit.chg_up): stopt met laden boven deze grens.

    AANNAME: grenzen 50-100% zijn niet onafhankelijk bevestigd als harde DJI-limiet (wel
    gebruikt als conservatieve default in een vergelijkbaar reverse-engineering-project,
    hiromo/ha-dji-power-bt, dat ditzelfde veld via BLE in plaats van REST instelt). Het
    generieke read-modify-write-mechanisme is bewezen (lamp/poort); dat het device na een
    PUT op chg_up ook daadwerkelijk eerder stopt met laden is NIET apart met hardware
    geverifieerd — alleen dat de server de wijziging accepteert en teruggeeft via GET.
    """
    pct = int(pct)

    def m(p):
        p["charge_limit"]["data"]["chg_up"] = pct

    out = apply_change(m, sn, token, client=client, verify=verify)
    if out["settings"] is not None:
        out["applied"] = out["settings"]["charge_limit"]["data"]["chg_up"] == pct
    return out


def set_field(path, value, sn=None, token=None, client=None, verify=True):
    """Generieke setter voor élk settings-veld (werkt voor de hele Power-lijn).

    path = dot-pad binnen het `data`-object, bv:
      'charge_limit.chg_up'   -> laadlimiet %
      'ac_hz_gear.gear'       -> AC-frequentie-gear (50/60Hz)
      'display.temp_unit'     -> °C/°F
      'es.chg_pct'            -> backup-reserve %
    Alleen velden waarvan het model `available` meldt, worden door het device geaccepteerd.
    value wordt als JSON-getal/-string doorgegeven.
    """
    keys = path.split(".")
    top = keys[0]

    def m(p):
        node = p[top]["data"]
        for k in keys[1:-1]:
            node = node[k]
        node[keys[-1]] = value

    return apply_change(m, sn, token, client=client, verify=verify)


def _report(out, label):
    ok = out["applied"]
    tag = "✓ toegepast" if ok else ("✗ niet toegepast" if ok is False else "? onbekend")
    print(f"{label}: server code={out['code']} ({out['message']}) -> {tag}")


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    if a[0] == "state":
        s = get_settings()
        print("lamp:", s["light"]["data"])
        print("poorten:")
        for x in s["power_sw"]["data"]:
            name = PORT_TYPE_NAMES.get(x["type"], "type" + str(x["type"]))
            print(f"  {name} ({x['type']}/{x['seq']}): {'AAN' if x['sw'] == PORT_ON else 'uit'}")
    elif a[0] == "light" and len(a) == 3 and a[1] == "bri":
        _report(set_light_brightness(int(a[2])), f"lamp helderheid {a[2]}%")
    elif a[0] == "light" and len(a) == 2:
        _report(set_light(a[1]), f"lamp {a[1]}")   # on|off|sos
    elif a[0] == "port" and len(a) == 4:
        _report(set_port(int(a[1]), int(a[2]), a[3] == "on"), f"poort {a[1]}/{a[2]} {a[3]}")
    elif a[0] == "set" and len(a) == 3:
        val = a[2]
        try:
            val = int(val)
        except ValueError:
            try:
                val = float(val)
            except ValueError:
                pass
        _report(set_field(a[1], val), f"{a[1]} = {val}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
