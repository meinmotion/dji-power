"""DJI-cloud-MQTT lezer (read-only stream).

Bundelt de voorheen dubbele connect+TLS+token-refresh-loop (dji_web.mqtt_loop en
de while-True in dji_ha.main). De DJI-MQTT-broker levert ~1/s device_osd en
device_state; het dynamische wachtwoord (~4u) wordt hier zelf ververst.

paho-mqtt v1/v2-compat wordt op deze ene plek geregeld: paho 2.x eist een
callback_api_version. We gebruiken de v1-callbacksignatuur (die alle bestaande
code al gebruikt) via CallbackAPIVersion.VERSION1 als dat bestaat.
"""
import ssl
import json
import threading

import paho.mqtt.client as mqtt

from . import const
from .rest import DjiAuthError


def make_client(client_id):
    """Maak een paho-client die de v1-callbacksignatuur gebruikt (werkt op 1.x én 2.x).

    Gebruikt zowel voor de DJI-cloud-verbinding als voor de lokale Mosquitto in de HA-bridge.
    """
    api = getattr(mqtt, "CallbackAPIVersion", None)
    if api is not None:                       # paho-mqtt 2.x
        return mqtt.Client(callback_api_version=api.VERSION1, client_id=client_id)
    return mqtt.Client(client_id=client_id)   # paho-mqtt 1.x


class CloudMqttReader:
    """Verbindt met de DJI-cloud-MQTT en roept callbacks aan bij inkomende berichten.

    on_osd(host):   host-dict uit een method:device_osd bericht.
    on_state(host): host-dict uit een method:device_state bericht.
    on_connect_change(connected: bool): optioneel, bij (dis)connect.
    on_auth_error(): optioneel; token ongeldig. De lus stopt dan (retry heeft geen zin).
    """

    def __init__(self, rest_client, on_osd=None, on_state=None,
                 on_connect_change=None, subscribe_events=False, line=const.LINE,
                 on_auth_error=None):
        self.rest = rest_client
        self.sn = rest_client.sn
        self.on_osd = on_osd
        self.on_state = on_state
        self.on_connect_change = on_connect_change
        self.on_auth_error = on_auth_error
        self.subscribe_events = subscribe_events
        self.line = line
        self._stop = threading.Event()
        self._client = None

    def stop(self):
        self._stop.set()
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass

    def _on_connect(self, c, u, flags, rc, *a):
        if self.on_connect_change:
            self.on_connect_change(rc == 0)
        c.subscribe(const.property_topic(self.sn, self.line), 0)
        if self.subscribe_events:
            c.subscribe(const.events_topic(self.sn, self.line), 0)

    def _on_message(self, c, u, msg):
        try:
            j = json.loads(msg.payload)
        except Exception:
            return
        method = j.get("method")
        host = j.get("data", {}).get("host", {})
        if method == "device_osd" and self.on_osd:
            self.on_osd(host)
        elif method == "device_state" and self.on_state:
            self.on_state(host)

    def run_forever(self):
        """Blokkerende lus met automatische token-refresh + reconnect. Stopt na stop()."""
        while not self._stop.is_set():
            try:
                creds = self.rest.get_mqtt_creds()
                host = creds["mqtt_domain"]
                port = int(creds["mqtt_port"])
                user = creds["user_uuid"]
                pwd = creds["user_token"]
                cid = creds.get("client_id", f"dji-{user}")
                expire = int(creds.get("expire", 14000))

                cli = make_client(cid)
                cli.username_pw_set(user, pwd)
                cli.tls_set(cert_reqs=ssl.CERT_NONE)
                cli.tls_insecure_set(True)
                cli.on_connect = self._on_connect
                cli.on_message = self._on_message
                cli.connect(host, port, 60)
                cli.loop_start()
                self._client = cli

                # draai tot ~5 min voor het token verloopt, dan verse creds + reconnect
                self._stop.wait(max(60, expire - 300))

                cli.loop_stop()
                cli.disconnect()
                self._client = None
                if self.on_connect_change:
                    self.on_connect_change(False)
            except DjiAuthError:
                if self.on_connect_change:
                    self.on_connect_change(False)
                print("[mqtt] token ongeldig of verlopen; opnieuw inloggen nodig")
                if self.on_auth_error:
                    self.on_auth_error()
                return
            except Exception as e:
                if self.on_connect_change:
                    self.on_connect_change(False)
                print("[mqtt] fout:", e)
                self._stop.wait(10)
