"""Config/secrets laden — één bron van waarheid.

Voorheen 8x gedupliceerd (secret()/_secret()/load_secret() + from_prefs()/_pref()).
Laadvolgorde is ongewijzigd: 1) omgevingsvariabele, 2) .dji_secrets (KEY=VALUE),
3) mem4_prefs.txt (de gedumpte Flutter-SharedPreferences, veld flutter.<key>).

De secrets-bestanden worden gezocht relatief aan de repo-root (twee niveaus boven
dit bestand: dji_power/config.py -> repo-root), zodat het werkt ongeacht de cwd.
"""
import os
import re
import html
from dataclasses import dataclass

from . import const

# repo-root = de map die .dji_secrets / mem4_prefs.txt bevat
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _root_path(name):
    return os.path.join(_ROOT, name)


def load_secret(name, default=None):
    """1) env, 2) .dji_secrets (KEY=VALUE), anders default."""
    if os.environ.get(name):
        return os.environ[name]
    p = _root_path(".dji_secrets")
    if os.path.exists(p):
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip()
    return default


def from_prefs(key):
    """Lees flutter.<key> uit de gedumpte SharedPreferences-XML (mem4_prefs.txt)."""
    p = _root_path("mem4_prefs.txt")
    if not os.path.exists(p):
        return None
    with open(p) as fh:
        m = re.search(r'name="flutter\.%s">([^<]*)</string>' % re.escape(key), fh.read())
    return html.unescape(m.group(1)) if m else None


def default_token():
    return load_secret("DJI_MEMBER_TOKEN") or from_prefs("user_token")


def default_sn():
    sn = load_secret("DJI_SN")
    if not sn:
        raise RuntimeError("Geen serienummer gevonden (zet DJI_SN in .dji_secrets of als omgevingsvariabele).")
    return sn


@dataclass
class Credentials:
    member_token: str
    sn: str

    @classmethod
    def load(cls):
        token = default_token()
        if not token:
            raise RuntimeError(
                "Geen DJI member-token gevonden (zet DJI_MEMBER_TOKEN in .dji_secrets "
                "of laat mem4_prefs.txt staan)."
            )
        return cls(member_token=token, sn=default_sn())
