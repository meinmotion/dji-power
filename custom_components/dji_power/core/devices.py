"""Gebonden apparaten uit de DJI-cloud-apparatenlijst.

`RestClient.get_device_list()` (GET /dy/app/api/v1/users/devices/list) levert per gebonden
Power-apparaat het serienummer en de BLE-koppelgegevens (`pair_info.pair_key`, dezelfde sleutel
die de Bluetooth-handshake nodig heeft). Met alleen het member-token volgen SN en pair_key dus
automatisch; dit is de basis van de keuze cloud/Bluetooth in de HA-config flow.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundDevice:
    sn: str
    name: str
    device_type: int | None = None
    device_mode: int | None = None
    online: bool | None = None
    is_share: bool = False
    pair_uuid: str | None = None
    pair_key: str | None = None      # None bij gedeelde apparaten: dan geen Bluetooth

    @property
    def label(self) -> str:
        """Korte weergavenaam voor een keuzelijst: 'DJI Power 1000 Mini (…110QPR)'."""
        return "%s (…%s)" % (self.name, self.sn[-6:])

    @property
    def ble_suffix(self) -> str:
        """Laatste 6 tekens van het SN; de adverteernaam is 'Power1000Mini-<suffix>'."""
        return self.sn[-6:].upper()


def parse_device_list(data) -> list[BoundDevice]:
    """Parse het `data`-deel van de apparatenlijst naar BoundDevice's (alleen `dy_devices`)."""
    out = []
    for dev in (data or {}).get("dy_devices") or []:
        base = dev.get("base_info") or {}
        pair = dev.get("pair_info") or {}
        sn = base.get("sn")
        if not sn:
            continue
        out.append(BoundDevice(
            sn=sn,
            name=base.get("name") or "DJI Power",
            device_type=base.get("device_type"),
            device_mode=base.get("device_mode"),
            online=base.get("online_status"),
            is_share=bool(base.get("is_share")),
            pair_uuid=pair.get("pair_uuid") or None,
            pair_key=pair.get("pair_key") or None,
        ))
    return out
