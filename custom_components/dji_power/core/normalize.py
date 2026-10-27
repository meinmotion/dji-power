"""Normalisatie van de ruwe DJI-cloud-MQTT payloads naar één platte state-dict.

Dit is de ENIGE plek waar de rekenregels staan. Voorheen dubbel: in Python
(dji_ha.update_from_osd/_from_state) én in JavaScript in het webdashboard
(charge_pct/100, temp/100, ...). De web-/data-endpoint levert nu deze
genormaliseerde velden, zodat de front-end-JS geen rekenwerk meer doet.

De 'on'/'off'/'SOS'/'normaal'-strings sluiten aan op de HA MQTT-discovery-payloads.
"""
from . import model


def normalize_osd(host):
    """method:device_osd -> {battery_pct, temp_c, remain_min, output_w, input_w, charging}.

    host = data["host"] uit het MQTT-bericht. Alleen aanwezige velden worden gezet.
    """
    out = {}
    b = host.get("battery", {})
    p = host.get("power_info", {})
    if "charge_pct" in b:
        out["battery_pct"] = round(b["charge_pct"] / 100)
    if "temp" in b:
        out["temp_c"] = round(b["temp"] / 100, 1)
    if "remain_time" in b:
        out["remain_min"] = b["remain_time"]
    if "output" in p:
        out["output_w"] = p["output"]
    if "input" in p:
        out["input_w"] = p["input"]
    out["charging"] = "on" if (p.get("input", 0) or 0) > 0 or b.get("charge_type", 0) else "off"
    return out


def normalize_state(host):
    """method:device_state (of het settings-object) -> lamp + poort-standen.

    Retour bevat, indien aanwezig: light_pct, light_on, light_fx, en per poort
    port_<type>_<seq> = 'on'/'off'.
    """
    out = {}
    light = (host.get("light") or {}).get("data")
    if light:
        st = light.get("state", 0)   # 1=uit, 2=aan, 3=SOS
        out["light_pct"] = light.get("pwm_v")
        out["light_on"] = "on" if st in (model.LIGHT_ON, model.LIGHT_SOS) else "off"
        out["light_fx"] = "SOS" if st == model.LIGHT_SOS else "normaal"
    psw = (host.get("power_sw") or {}).get("data")
    if psw:
        for s in psw:
            out[model.port_key(s["type"], s["seq"])] = "on" if s.get("sw") == model.PORT_ON else "off"
    return out
