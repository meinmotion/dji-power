"""Vaste constanten en URL-helpers voor de DJI-cloud-API.

Gecentraliseerd uit de losse scripts (voorheen 4x gedupliceerd in dji_control.py,
dji_ha.py, dji_web.py en dji_cloud.py).
"""

API_BASE = "https://home-api-vg.djigate.com"   # regio 2 (EU)
AUTH_PATH = "/app/api/v1/users/auth/token"
UA = "DJI-Home/1.6.3 (Android)"
LINE = "dy"                                     # productlijn-prefix (Power); bevestigd via SUBACK


def settings_url(sn):
    """REST-endpoint voor de volledige settings (GET + read-modify-write PUT)."""
    return f"{API_BASE}/dy/app/api/v1/devices/{sn}/settings"


def device_list_path():
    return "/dy/app/api/v1/users/devices/list"


def property_topic(sn, line=LINE):
    return f"forward/{line}/thing/product/{sn}/property"


def events_topic(sn, line=LINE):
    return f"forward/{line}/thing/product/{sn}/events"
