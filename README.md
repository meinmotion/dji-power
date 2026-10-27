# DJI Power 1000 Mini → Home Assistant (remote, via DJI-cloud)

Leest de DJI Power 1000 Mini op afstand uit via de DJI-cloud (MQTT) en publiceert de
status naar Home Assistant met MQTT-discovery. **Uitlezen én besturing werken volledig,
op afstand, zonder emulator** (zie onderaan).

## Hoe het werkt
1. **Auth**: `GET https://home-api-vg.djigate.com/app/api/v1/users/auth/token?reason=mqtt`
   met header `x-member-token: <member-token>` → MQTT-credentials (broker, user_uuid,
   dynamisch wachtwoord ~4u geldig).
2. **MQTT** (TLS, `crobot-mqtt-us.djigate.com:8883`): subscribe op
   `forward/dy/thing/product/<SN>/property` (+ `/events`).
3. **Status** (`method:device_osd`, ~1/s): accu, watt in/uit, temp, resterende tijd, poorten.
   **Poort-schakelaars + lamp** komen via `method:device_state` (`power_sw`, `light`).

## Structuur
De deelbare logica staat in het framework-agnostische core-package **`dji_power/`**; de
frontends (webdashboard, HA-bridge, HACS-integratie) zijn dunne consumers daarbovenop.

| Pad | Doel |
|---|---|
| `dji_power/` | **Core-package** (bron van waarheid): `config`, `rest`, `mqtt`, `model`, `normalize`, `control`, `hub`. Framework-agnostisch, geen HA-afhankelijkheden. |
| `dji_power/hub.py` | `DjiPowerHub`: bindt REST + cloud-MQTT + normalisatie tot één databron met `subscribe(callback)` en control-passthrough. |
| `apps/ha_bridge.py` | **Externe HA-bridge**: DJI-MQTT → Home Assistant (MQTT-discovery), incl. **schakelbare** lamp + poorten. Bovenop `DjiPowerHub`. |
| `apps/web.py` | Lokaal dashboard (http://localhost:8765) met alle live waarden **en klikbare schakelaars**. |
| `custom_components/dji_power/` | **Native HACS-integratie** (config_flow + push-coordinator + entities). Draait ín HA, geen Mosquitto nodig. |
| `dji_control.py` | Backwards-compat shim voor de CLI (`dji_power.control`). |
| `tools/re/` | Reverse-engineering-/debug-scripts (o.a. `dji_cloud.py`). |
| `tools/fix_elf.py` | Herstelt de door de packer gestripte `.dynsym` in `libapp.so` (voor Blutter). |
| `.dji_secrets` | Jouw geheimen (gitignored). Kopie van `.dji_secrets.example`. |
| `mem4_prefs.txt` | Bevat het member-token (`flutter.user_token`), uit de emulator-geheugendump. |
| `CREDITS.md` | Externe tools/projecten die credit verdienen. |
| `PROTOCOL_CLOUD.md` / `FINDINGS.md` | Protocol + volledige reverse-engineering-bevindingen. |

## Opzetten (standalone: bridge + webdashboard)
```bash
./.venv/bin/pip install -r requirements.txt
cp .dji_secrets.example .dji_secrets     # vul je HA-MQTT-broker (Mosquitto) in
./.venv/bin/python apps/ha_bridge.py     # HA-bridge
./.venv/bin/python apps/web.py           # of het lokale dashboard op :8765
```

## Home Assistant via HACS (native integratie)
De map `custom_components/dji_power/` is een volwaardige HA-integratie: installeer de repo
als custom repository in HACS, herstart HA en voeg **DJI Power** toe via *Instellingen →
Integraties* (config_flow vraagt om je member-token + SN). Dit draait ín HA en heeft **geen**
aparte daemon of Mosquitto nodig. De core wordt meegebundeld onder
`custom_components/dji_power/core/` (sync met `tools/sync_core.sh`).
In Home Assistant verschijnt automatisch het device **"DJI Power 1000 Mini"** met sensors
(accu %, uitgaand/ingaand vermogen, batterijtemp, resterende tijd, lamphelderheid) en
binaire sensors (laadt, lamp, en de poorten AC/USB-C/USB-A/SDC).

Draai `dji_ha.py` ergens dat altijd aanstaat (Mac, Pi, of als HA-addon/systemd-service).

## Tokens / levensduur
- **MQTT-token** (~4u): wordt **automatisch** ververst door `dji_ha.py`. Niks te doen.
- **Member-token** (`US_…`): lang geldig (dagen/weken). Verloopt het ooit, dan opnieuw uit
  de app halen (emulator-geheugendump, zie `RE-STEPS.md`) of via een nagebouwde
  `account.dji.com`-login een vers token oogsten.

## Besturing — schone REST-API (`dji_control.py`), GEEN emulator
Schakelen werkt volledig via de cloud-REST-API:

```bash
./.venv/bin/python dji_control.py state              # lamp + poort-standen
./.venv/bin/python dji_control.py light on|off|sos   # lamp: aan / uit / SOS-modus
./.venv/bin/python dji_control.py light bri 50        # helderheid 10-100%
./.venv/bin/python dji_control.py port 2 1 off       # poort schakelen (2/1 = AC; 'off' cut de last!)
```

De lamp heeft drie standen (enum `Mya`): **1=uit, 2=aan** (helderheid = `pwm_v`, 10-100%),
**3=SOS**. De poort-schakelaar `sw` is óók een enum (`Lsa`), geen boolean:
**1=aan (open), 2=uit (close)** — `sw:2` betekent dus *uit*, niet aan.

En vanuit het **dashboard** (`http://localhost:8765`): uit/aan/SOS-schuifschakelaars, een
helderheids-slider en poort-schakelaars — allemaal direct via de REST-call. Geen emulator, geen
adb, geen UI-automatisering. In **Home Assistant** verschijnt de lamp als `light`-entiteit met
helderheid en een SOS-effect; de poorten als schakelbare `switch`-entiteiten.

**Optimistische UI:** de cloud-bevestiging na een schakelactie duurt enkele seconden (de
`app→cloud→device→cloud`-round-trip is inherent aan de cloud — DJI's eigen app is even traag).
Het dashboard toont daarom de nieuwe stand direct en zet de schakelaar op ⏳/disabled tot de
cloud bevestigt (snelle polling + de MQTT `device_state`-push; timeout ~12s). De **live**
waarden (accu/watt/temp via MQTT `device_osd`) komen al ~1×/s binnen.

### Hoe (gevonden via Blutter-decompilatie)
De control-endpoint is **`PUT /dy/app/api/v1/devices/<SN>/settings`** met **alléén
`x-member-token`** (geen Sign-Mc). De app doet **read-modify-write van het VOLLEDIGE
settings-object**:

```json
{"double_check": false, "param": { <alle settings, met 1 veld gewijzigd> }}
```

Een partieel `param` (bv. alleen `{"light": …}`) geeft `121001 parameter error`; alleen het
complete object wordt geaccepteerd. De server antwoordt vaak met `121804 "Device response
timeout"`, maar de wijziging wordt wél toegepast — `dji_control.py` verifieert daarom via een
GET.

Dit body-formaat was niet te raden en niet live te onderscheppen (Flutter negeert de proxy;
frida crasht op AppGuard). Het is gereconstrueerd met **Blutter** op `libapp.so`. De packer
(zxprotect) had de `.dynsym` gestript, waardoor Blutter de vier Dart-snapshot-symbolen niet
vond; `tools/fix_elf.py` herstelt die (snapshot-blobs op vaddr==offset, adressen via de
snapshot-magic + instructie-ImageHeaders). Zie `RE-STEPS.md`.

`tools/re/dji_tap.py` (emulator-UI-automatisering) bestaat nog als fallback, maar is niet meer nodig.

### Meer instellingen (generieke setter)
Elk veld in het settings-object is via dezelfde read-modify-write bereikbaar:

```bash
./.venv/bin/python dji_control.py set charge_limit.chg_up 90    # laadlimiet 90%
./.venv/bin/python dji_control.py set ac_hz_gear.gear 2         # AC-frequentie (50/60Hz)
./.venv/bin/python dji_control.py set display.temp_unit 2       # °C/°F
./.venv/bin/python dji_control.py set es.chg_pct 80             # backup-reserve %
```

Nog niet in de UI, maar meteen bruikbaar: `charge_limit`, `ac_chg_gear` (laadsnelheid),
`ac_hz_gear`, `display`, `low_power_alert`, `ac_out_mem`, `es`, en model-specifiek
`low_power_mode`, `overcharge_mode`, `input_p_stepless`, `host_soc_value`, `pv_es` (zonne/MPPT),
`grid_conn_es` (netgekoppeld), `parallels`. Elk veld heeft een `available`-vlag (`false` = dit
model heeft de functie niet).

## Modellen / compatibiliteit
De app en cloud-API zijn identiek voor de **hele Power-lijn**: **Power 1000, 1000 Mini**
(deze, type 272), **1000 V/V2, 2000 en 2000 Mini**. Zelfde endpoints, settings-model en enums —
uitlezen én besturing werken dus op elk van deze modellen. Per model verschillen alleen:
- de **poort-layout** (`power_sw`): `dji_web.py` en `dji_ha.py` lezen die **dynamisch** uit, dus
  de UI/entiteiten passen zich vanzelf aan (een 2000 met andere poorten werkt out-of-the-box);
- de **beschikbare functies** (`available`-vlag): bv. zonne-laden (`pv_es`/MPPT), netgekoppeld
  laden (`grid_conn_es`) en parallel koppelen (`parallels`) zijn op grotere modellen aanwezig en
  via de generieke setter meteen te bedienen.

Enige aanname: het device hangt aan een DJI-account waarvan je het `x-member-token` hebt.
