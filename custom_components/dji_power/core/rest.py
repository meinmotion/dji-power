"""REST-client voor de DJI-cloud-API.

Bundelt de voorheen gedupliceerde headers/creds/settings-calls (dji_control.headers,
dji_web.rest_headers/get, dji_ha.get_mqtt_creds, dji_cloud.get_mqtt_creds).

- get_settings / put_settings: de volledige settings (voor read-modify-write besturing).
- get_device_list: accu %, online, laadt, poort-layout (REST-kant van het webdashboard).
- get_mqtt_creds: auth-token -> MQTT-credentials (broker, user_uuid, dynamisch wachtwoord).
"""
import requests

from . import const

# Antwoordcode van de DJI-cloud bij een ongeldig/verlopen member-token ("log opnieuw in").
# Komt als HTTP 200 met deze code in de body (FINDINGS.md), niet als 401.
AUTH_CODES = {121010}


class DjiAuthError(Exception):
    """Het member-token is ongeldig of verlopen; opnieuw inloggen is nodig."""


def check_auth(r):
    """Gooi DjiAuthError als het antwoord op een ongeldig token wijst."""
    if r.status_code in (401, 403):
        raise DjiAuthError("HTTP %s" % r.status_code)
    try:
        code = r.json().get("code")
    except Exception:
        return
    if code is not None and str(code).isdigit() and int(code) in AUTH_CODES:
        raise DjiAuthError(str(r.json().get("message") or code))


class RestClient:
    def __init__(self, member_token, sn, api_base=const.API_BASE, timeout=15):
        self.member_token = member_token
        self.sn = sn
        self.api_base = api_base
        self.timeout = timeout

    def headers(self):
        return {
            "x-member-token": self.member_token,
            "User-Agent": const.UA,
            "X-DJI-locale": "en",
            "Content-Type": "application/json",
        }

    # ---- generieke GET ----
    def get(self, path):
        r = requests.get(self.api_base + path, headers=self.headers(), timeout=self.timeout)
        check_auth(r)
        r.raise_for_status()
        return r.json().get("data", {})

    # ---- settings (read-modify-write) ----
    def _settings_url(self):
        return const.settings_url(self.sn)

    def get_settings(self):
        r = requests.get(self._settings_url(), headers=self.headers(), timeout=self.timeout)
        check_auth(r)
        r.raise_for_status()
        return r.json()["data"]

    def put_settings(self, param, double_check=False):
        """PUT het VOLLEDIGE settings-object terug. Retour: het ruwe response-JSON."""
        r = requests.put(self._settings_url(), headers=self.headers(),
                         json={"double_check": double_check, "param": param},
                         timeout=max(self.timeout, 30))
        try:
            return r.json()
        except Exception:
            return {}

    # ---- device-lijst (accu %, online, poort-layout) ----
    def get_device_list(self):
        return self.get(const.device_list_path())

    # ---- MQTT-credentials (auth-token, ~4u geldig) ----
    def get_mqtt_creds(self):
        r = requests.get(self.api_base + const.AUTH_PATH, params={"reason": "mqtt"},
                         headers=self.headers(), timeout=20)
        check_auth(r)
        r.raise_for_status()
        j = r.json()
        return j.get("data", j)   # soms genest onder "data"
