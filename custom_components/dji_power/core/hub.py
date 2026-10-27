"""DjiPowerHub — bindt REST + cloud-MQTT + normalisatie tot één databron.

Dit is de ontkoppelingslaag: elke frontend (webdashboard, HA-bridge, HACS-coordinator)
draait een DjiPowerHub in-proces en hangt via subscribe(callback) aan de
genormaliseerde state. Besturing gaat via de control-passthrough (REST).

Er is bewust GEEN interne MQTT-broker: de hub is een gewone Python-library.
Een Mosquitto-"engine" is later triviaal toe te voegen als één extra consumer
(hub.subscribe(publish_to_mosquitto)) zónder de core te wijzigen.
"""
import threading

from . import config, control, normalize
from .model import discover_ports
from .rest import RestClient
from .mqtt import CloudMqttReader


class DjiPowerHub:
    def __init__(self, member_token=None, sn=None, subscribe_events=False):
        creds = None
        if member_token is None or sn is None:
            creds = config.Credentials.load()
        self.member_token = member_token or creds.member_token
        self.sn = sn or creds.sn
        self.rest = RestClient(self.member_token, self.sn)
        self.reader = CloudMqttReader(
            self.rest,
            on_osd=self._on_osd,
            on_state=self._on_state,
            on_connect_change=self._on_connect_change,
            subscribe_events=subscribe_events,
        )
        self._state = {}
        self._lock = threading.Lock()
        self._listeners = []
        self.connected = False
        self._reader_thread = None

    # ---- state ----
    @property
    def state(self):
        with self._lock:
            return dict(self._state)

    def _apply(self, patch):
        if not patch:
            return
        with self._lock:
            self._state.update(patch)
            snapshot = dict(self._state)
        for cb in list(self._listeners):
            try:
                cb(snapshot)
            except Exception as e:
                print("[hub] listener-fout:", e)

    def subscribe(self, callback):
        """Roep callback(state_dict) aan bij elke state-wijziging. Retour: unsubscribe-fn."""
        self._listeners.append(callback)
        return lambda: self._listeners.remove(callback) if callback in self._listeners else None

    # ---- MQTT-callbacks ----
    def _on_osd(self, host):
        self._apply(normalize.normalize_osd(host))

    def _on_state(self, host):
        self._apply(normalize.normalize_state(host))

    def _on_connect_change(self, connected):
        self.connected = connected

    # ---- lifecycle ----
    def prime_from_settings(self):
        """Vul de initiële state uit een REST-GET van de settings (voor de eerste MQTT-push)."""
        try:
            settings = self.rest.get_settings()
        except Exception as e:
            print("[hub] initiële settings-GET faalde:", e)
            return None
        self._apply(normalize.normalize_state(settings))
        return settings

    def discover_ports(self):
        """Poortenlijst (type, seq, naam, icon) uit de live settings."""
        settings = self.rest.get_settings()
        return discover_ports(settings["power_sw"]["data"])

    def start(self):
        """Start de MQTT-reader in een achtergrond-thread."""
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_thread = threading.Thread(target=self.reader.run_forever, daemon=True)
        self._reader_thread.start()

    def stop(self):
        self.reader.stop()

    # ---- besturing (REST-passthrough) ----
    def set_light(self, mode, verify=False):
        return control.set_light(mode, client=self.rest, verify=verify)

    def set_light_brightness(self, pct, verify=False):
        return control.set_light_brightness(pct, client=self.rest, verify=verify)

    def set_port(self, ptype, seq, on, verify=False):
        return control.set_port(ptype, seq, on, client=self.rest, verify=verify)

    def set_field(self, path, value, verify=False):
        return control.set_field(path, value, client=self.rest, verify=verify)
