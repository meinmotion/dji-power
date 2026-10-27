"""DJI DUML V1 frame-codec voor de BLE-transportlaag van de DJI Power.

Gereconstrueerd uit de Blutter-decompilatie van libapp.so (klasse ProtocolV1Base,
out_blutter/pp.txt). De twee CRC-lookup-tabellen hieronder zijn 1-op-1 overgenomen
uit de Dart object-pool:
    CRC8_TABLE  <- pp.txt:15057  ([0, 0x5e, 0xbc, 0xe2, ...])  header-check
    CRC16_TABLE <- pp.txt:15071  ([0, 0x1189, 0x2312, ...])    frame-check

Frame-layout (DJI DUML V1):
    off 0      : 0x55                     magic
    off 1      : length & 0xFF            totale framelengte, low 8 bits
    off 2      : (length>>8 & 0x03) | (version<<2)   length hi 2b + version 6b
    off 3      : CRC-8 over byte 0..2     header-check
    off 4      : sender                   bronadres (COMM_DEV_TYPE)
    off 5      : receiver                 doeladres (COMM_DEV_TYPE)
    off 6..7   : seq id (16-bit LE)
    off 8      : cmd_type                 pack<<7 | ack<<5 | encrypt[bits 0..2]
    off 9      : cmd_set
    off 10     : cmd_id
    off 11..   : payload
    laatste 2  : CRC-16 (LE) over byte 0 .. einde-payload

GEVALIDEERD (2026-08-20) tegen vier echte DJI-frames uit publieke prior art
(o-gs/dji-firmware-tools, yigitkonur/lib-osmo-ble): zowel parse als build reproduceren
die frames byte-exact, inclusief beide CRC's. Zie GOLDEN in self_test().

Version is in echte frames ALTIJD 1 (byte 2 == 0x04 zolang length < 256); een frame met
version 0 is geen geldig DUML-v1-frame, ook al klopt de header-CRC over zichzelf.
"""
from __future__ import annotations
from dataclasses import dataclass, field

MAGIC = 0x55

# --- COMM_DEV_TYPE: de sender/receiver-bytes (dji-firmware-tools). De DJI-app
#     adresseert zichzelf als MOBILE_APP (0x02); 0x0A is de PC/Assistant-id. ---
ADDR_ANY = 0x00
ADDR_CAMERA = 0x01
ADDR_APP = 0x02          # MOBILE_APP -- wat de DJI Home-app gebruikt
ADDR_FC = 0x03
ADDR_GIMBAL = 0x04
ADDR_CENTER = 0x05
ADDR_RC = 0x06
ADDR_WIFI = 0x07
ADDR_PC = 0x0A           # de oude waarde van ADDR_APP; DJI Assistant
ADDR_BATTERY = 0x0B
ADDR_STATION = 0x16
ADDR_PMU = 0x1D

DEV_TYPE_NAMES = {
    ADDR_ANY: "any", ADDR_CAMERA: "camera", ADDR_APP: "app", ADDR_FC: "fc",
    ADDR_GIMBAL: "gimbal", ADDR_CENTER: "center", ADDR_RC: "rc", ADDR_WIFI: "wifi",
    ADDR_PC: "pc", ADDR_BATTERY: "battery", ADDR_STATION: "station", ADDR_PMU: "pmu",
}

# --- cmd_type (byte 8) = pack_type<<7 | ack_type<<5 | encrypt_type[bits 0..2] ---
PKT_REQUEST, PKT_RESPONSE = 0, 1
ACK_NONE, ACK_BEFORE, ACK_AFTER = 0, 1, 2
ENC_NONE, ENC_AES128, ENC_SELF, ENC_XOR = 0, 1, 2, 3
ENC_DES56, ENC_DES112, ENC_AES192, ENC_AES256 = 4, 5, 6, 7


def cmd_type(pack: int = PKT_REQUEST, ack: int = ACK_AFTER, enc: int = ENC_NONE) -> int:
    """Stel byte 8 samen. `enc != 0` is de `needAesDecrypt`-vlag uit de app."""
    return ((pack & 0x01) << 7) | ((ack & 0x03) << 5) | (enc & 0x07)

CRC8_TABLE = [
    0x00, 0x5e, 0xbc, 0xe2, 0x61, 0x3f, 0xdd, 0x83,
    0xc2, 0x9c, 0x7e, 0x20, 0xa3, 0xfd, 0x1f, 0x41,
    0x9d, 0xc3, 0x21, 0x7f, 0xfc, 0xa2, 0x40, 0x1e,
    0x5f, 0x01, 0xe3, 0xbd, 0x3e, 0x60, 0x82, 0xdc,
    0x23, 0x7d, 0x9f, 0xc1, 0x42, 0x1c, 0xfe, 0xa0,
    0xe1, 0xbf, 0x5d, 0x03, 0x80, 0xde, 0x3c, 0x62,
    0xbe, 0xe0, 0x02, 0x5c, 0xdf, 0x81, 0x63, 0x3d,
    0x7c, 0x22, 0xc0, 0x9e, 0x1d, 0x43, 0xa1, 0xff,
    0x46, 0x18, 0xfa, 0xa4, 0x27, 0x79, 0x9b, 0xc5,
    0x84, 0xda, 0x38, 0x66, 0xe5, 0xbb, 0x59, 0x07,
    0xdb, 0x85, 0x67, 0x39, 0xba, 0xe4, 0x06, 0x58,
    0x19, 0x47, 0xa5, 0xfb, 0x78, 0x26, 0xc4, 0x9a,
    0x65, 0x3b, 0xd9, 0x87, 0x04, 0x5a, 0xb8, 0xe6,
    0xa7, 0xf9, 0x1b, 0x45, 0xc6, 0x98, 0x7a, 0x24,
    0xf8, 0xa6, 0x44, 0x1a, 0x99, 0xc7, 0x25, 0x7b,
    0x3a, 0x64, 0x86, 0xd8, 0x5b, 0x05, 0xe7, 0xb9,
    0x8c, 0xd2, 0x30, 0x6e, 0xed, 0xb3, 0x51, 0x0f,
    0x4e, 0x10, 0xf2, 0xac, 0x2f, 0x71, 0x93, 0xcd,
    0x11, 0x4f, 0xad, 0xf3, 0x70, 0x2e, 0xcc, 0x92,
    0xd3, 0x8d, 0x6f, 0x31, 0xb2, 0xec, 0x0e, 0x50,
    0xaf, 0xf1, 0x13, 0x4d, 0xce, 0x90, 0x72, 0x2c,
    0x6d, 0x33, 0xd1, 0x8f, 0x0c, 0x52, 0xb0, 0xee,
    0x32, 0x6c, 0x8e, 0xd0, 0x53, 0x0d, 0xef, 0xb1,
    0xf0, 0xae, 0x4c, 0x12, 0x91, 0xcf, 0x2d, 0x73,
    0xca, 0x94, 0x76, 0x28, 0xab, 0xf5, 0x17, 0x49,
    0x08, 0x56, 0xb4, 0xea, 0x69, 0x37, 0xd5, 0x8b,
    0x57, 0x09, 0xeb, 0xb5, 0x36, 0x68, 0x8a, 0xd4,
    0x95, 0xcb, 0x29, 0x77, 0xf4, 0xaa, 0x48, 0x16,
    0xe9, 0xb7, 0x55, 0x0b, 0x88, 0xd6, 0x34, 0x6a,
    0x2b, 0x75, 0x97, 0xc9, 0x4a, 0x14, 0xf6, 0xa8,
    0x74, 0x2a, 0xc8, 0x96, 0x15, 0x4b, 0xa9, 0xf7,
    0xb6, 0xe8, 0x0a, 0x54, 0xd7, 0x89, 0x6b, 0x35,
]

CRC16_TABLE = [
    0x0000, 0x1189, 0x2312, 0x329b, 0x4624, 0x57ad, 0x6536, 0x74bf,
    0x8c48, 0x9dc1, 0xaf5a, 0xbed3, 0xca6c, 0xdbe5, 0xe97e, 0xf8f7,
    0x1081, 0x0108, 0x3393, 0x221a, 0x56a5, 0x472c, 0x75b7, 0x643e,
    0x9cc9, 0x8d40, 0xbfdb, 0xae52, 0xdaed, 0xcb64, 0xf9ff, 0xe876,
    0x2102, 0x308b, 0x0210, 0x1399, 0x6726, 0x76af, 0x4434, 0x55bd,
    0xad4a, 0xbcc3, 0x8e58, 0x9fd1, 0xeb6e, 0xfae7, 0xc87c, 0xd9f5,
    0x3183, 0x200a, 0x1291, 0x0318, 0x77a7, 0x662e, 0x54b5, 0x453c,
    0xbdcb, 0xac42, 0x9ed9, 0x8f50, 0xfbef, 0xea66, 0xd8fd, 0xc974,
    0x4204, 0x538d, 0x6116, 0x709f, 0x0420, 0x15a9, 0x2732, 0x36bb,
    0xce4c, 0xdfc5, 0xed5e, 0xfcd7, 0x8868, 0x99e1, 0xab7a, 0xbaf3,
    0x5285, 0x430c, 0x7197, 0x601e, 0x14a1, 0x0528, 0x37b3, 0x263a,
    0xdecd, 0xcf44, 0xfddf, 0xec56, 0x98e9, 0x8960, 0xbbfb, 0xaa72,
    0x6306, 0x728f, 0x4014, 0x519d, 0x2522, 0x34ab, 0x0630, 0x17b9,
    0xef4e, 0xfec7, 0xcc5c, 0xddd5, 0xa96a, 0xb8e3, 0x8a78, 0x9bf1,
    0x7387, 0x620e, 0x5095, 0x411c, 0x35a3, 0x242a, 0x16b1, 0x0738,
    0xffcf, 0xee46, 0xdcdd, 0xcd54, 0xb9eb, 0xa862, 0x9af9, 0x8b70,
    0x8408, 0x9581, 0xa71a, 0xb693, 0xc22c, 0xd3a5, 0xe13e, 0xf0b7,
    0x0840, 0x19c9, 0x2b52, 0x3adb, 0x4e64, 0x5fed, 0x6d76, 0x7cff,
    0x9489, 0x8500, 0xb79b, 0xa612, 0xd2ad, 0xc324, 0xf1bf, 0xe036,
    0x18c1, 0x0948, 0x3bd3, 0x2a5a, 0x5ee5, 0x4f6c, 0x7df7, 0x6c7e,
    0xa50a, 0xb483, 0x8618, 0x9791, 0xe32e, 0xf2a7, 0xc03c, 0xd1b5,
    0x2942, 0x38cb, 0x0a50, 0x1bd9, 0x6f66, 0x7eef, 0x4c74, 0x5dfd,
    0xb58b, 0xa402, 0x9699, 0x8710, 0xf3af, 0xe226, 0xd0bd, 0xc134,
    0x39c3, 0x284a, 0x1ad1, 0x0b58, 0x7fe7, 0x6e6e, 0x5cf5, 0x4d7c,
    0xc60c, 0xd785, 0xe51e, 0xf497, 0x8028, 0x91a1, 0xa33a, 0xb2b3,
    0x4a44, 0x5bcd, 0x6956, 0x78df, 0x0c60, 0x1de9, 0x2f72, 0x3efb,
    0xd68d, 0xc704, 0xf59f, 0xe416, 0x90a9, 0x8120, 0xb3bb, 0xa232,
    0x5ac5, 0x4b4c, 0x79d7, 0x685e, 0x1ce1, 0x0d68, 0x3ff3, 0x2e7a,
    0xe70e, 0xf687, 0xc41c, 0xd595, 0xa12a, 0xb0a3, 0x8238, 0x93b1,
    0x6b46, 0x7acf, 0x4854, 0x59dd, 0x2d62, 0x3ceb, 0x0e70, 0x1ff9,
    0xf78f, 0xe606, 0xd49d, 0xc514, 0xb1ab, 0xa022, 0x92b9, 0x8330,
    0x7bc7, 0x6a4e, 0x58d5, 0x495c, 0x3de3, 0x2c6a, 0x1ef1, 0x0f78,
]


def crc8(data: bytes, init: int = 0x77) -> int:
    """DJI header-CRC-8 (poly via CRC8_TABLE). init 0x77 is de klassieke DUML-startwaarde."""
    c = init
    for b in data:
        c = CRC8_TABLE[(c ^ b) & 0xFF]
    return c & 0xFF


def crc16(data: bytes, init: int = 0x3692) -> int:
    """DJI frame-CRC-16 (poly via CRC16_TABLE). init 0x3692 is de klassieke DUML-startwaarde."""
    c = init
    for b in data:
        c = ((c >> 8) ^ CRC16_TABLE[(c ^ b) & 0xFF]) & 0xFFFF
    return c & 0xFFFF


@dataclass
class Frame:
    cmd_set: int
    cmd_id: int
    payload: bytes = b""
    sender: int = ADDR_APP
    receiver: int = ADDR_ANY
    seq: int = 0
    cmd_type: int = 0x00     # pack<<7 | ack<<5 | encrypt; zie cmd_type()
    version: int = 1         # echte DJI-frames hebben altijd version 1

    # --- afgeleide velden uit cmd_type (byte 8) ---
    @property
    def pack_type(self) -> int:
        return (self.cmd_type >> 7) & 0x01

    @property
    def ack_type(self) -> int:
        return (self.cmd_type >> 5) & 0x03

    @property
    def encrypt_type(self) -> int:
        """0 = plaintext. Niet-nul is de `needAesDecrypt`-vlag; 7 = AES-256."""
        return self.cmd_type & 0x07

    @property
    def is_response(self) -> bool:
        return self.pack_type == PKT_RESPONSE

    def build(self, cipher=None) -> bytes:
        """Serialiseer naar een DUML-v1-frame.

        `cipher` (een dji_crypto.ModelCipher) wordt gebruikt als encrypt_type != 0:
        de payload gaat versleuteld het frame in, vóór de CRC-16 wordt berekend.
        """
        payload = self.payload
        if self.encrypt_type != ENC_NONE:
            if cipher is None:
                raise ValueError("encrypt_type=%d maar geen cipher meegegeven"
                                 % self.encrypt_type)
            payload = cipher.encrypt(payload)
        total = 13 + len(payload)               # 11-byte header + payload + 2-byte CRC16
        if total > 0x3FF:
            raise ValueError("frame te lang (>1023); length-veld is 10 bits")
        hdr = bytes([
            MAGIC,
            total & 0xFF,
            ((total >> 8) & 0x03) | ((self.version & 0x3F) << 2),
        ])
        hdr += bytes([crc8(hdr)])
        body = hdr + bytes([
            self.sender & 0xFF,
            self.receiver & 0xFF,
            self.seq & 0xFF, (self.seq >> 8) & 0xFF,
            self.cmd_type & 0xFF,
            self.cmd_set & 0xFF,
            self.cmd_id & 0xFF,
        ]) + payload
        c = crc16(body)
        return body + bytes([c & 0xFF, (c >> 8) & 0xFF])


def parse_frame(buf: bytes, cipher=None) -> Frame:
    """Parse en valideer een volledig frame. Gooit ValueError bij magic/CRC-fout.

    Is encrypt_type != 0 en is er een `cipher`, dan wordt de payload na de CRC-check
    ontsleuteld. Zonder cipher blijft hij versleuteld (de caller ziet het aan
    `frame.encrypt_type`).
    """
    if len(buf) < 13:
        raise ValueError("te kort")
    if buf[0] != MAGIC:
        raise ValueError("magic ongeldig")
    total = buf[1] | ((buf[2] & 0x03) << 8)
    version = buf[2] >> 2
    if crc8(buf[0:3]) != buf[3]:
        raise ValueError("header-CRC-8 ongeldig")
    if len(buf) < total:
        raise ValueError("frame nog niet compleet: %d < %d" % (len(buf), total))
    frame = buf[:total]
    got = frame[-2] | (frame[-1] << 8)
    if crc16(frame[:-2]) != got:
        raise ValueError("frame-CRC-16 ongeldig")
    f = Frame(
        cmd_set=frame[9], cmd_id=frame[10], payload=frame[11:-2],
        sender=frame[4], receiver=frame[5],
        seq=frame[6] | (frame[7] << 8), cmd_type=frame[8], version=version,
    )
    if f.encrypt_type != ENC_NONE and cipher is not None:
        f.payload = cipher.decrypt(f.payload)
    return f


class Reassembler:
    """Buffer inkomende BLE-notify-chunks (fff4) en lever complete frames op."""
    def __init__(self):
        self._buf = bytearray()

    def feed(self, chunk: bytes):
        self._buf.extend(chunk)
        out = []
        while True:
            # sync op magic
            i = self._buf.find(MAGIC)
            if i < 0:
                self._buf.clear(); break
            if i > 0:
                del self._buf[:i]
            if len(self._buf) < 13:
                break
            total = self._buf[1] | ((self._buf[2] & 0x03) << 8)
            if total < 13 or crc8(bytes(self._buf[0:3])) != self._buf[3]:
                del self._buf[0]          # valse magic; schuif door
                continue
            if len(self._buf) < total:
                break                      # wacht op meer
            frame_bytes = bytes(self._buf[:total])
            del self._buf[:total]
            try:
                out.append(parse_frame(frame_bytes))
            except ValueError:
                pass
        return out


# --- Golden vectors: ECHTE DJI-frames uit publieke prior art. Ze bewijzen dat onze
#     codec het protocol reproduceert i.p.v. alleen intern consistent te zijn.
#     [1][2] o-gs/dji-firmware-tools (comm_og_service_tool.py, dry-test-blokken)
#     [3][4] yigitkonur/lib-osmo-ble (PROTOCOL.md + analysis/)
#     Voeg elk frame dat we van het echte device terugkrijgen hier toe.
GOLDEN = [
    # (hex, sender, receiver, seq, cmd_type, cmd_set, cmd_id, payload_hex)
    ("550e0466030a9da58003df00a792",
     0x03, 0x0a, 0xa59d, 0x80, 0x03, 0xdf, "00"),
    ("551904e4030a9ea58003e0000000002f87ca7a8601000055e7",
     0x03, 0x0a, 0xa59e, 0x80, 0x03, 0xe0, "000000002f87ca7a86010000"),
    ("552204ea020780924007450f30303137343933313932383631303204353136302e42",
     0x02, 0x07, 0x9280, 0x40, 0x07, 0x45,
     "0f3030313734393331393238363130320435313630"),
    ("551104920208ffab40028e00011c003bc8",
     0x02, 0x08, 0xabff, 0x40, 0x02, 0x8e, "00011c00"),
]


def self_test():
    # --- 1. CRC-inits. Deze twee asserts staan hier zodat niemand ze later
    #        "verbetert" naar 0xEE/0x496C -- dat zijn dezelfde waarden in de
    #        reflected conventie, en fout in combinatie met onze tabellen. ---
    assert crc8(b"\x55\x0e\x04") == 0x66, "CRC-8 init 0x77 klopt niet meer"
    assert crc16(bytes.fromhex("550e0466030a9da58003df00")) == 0x92a7, \
        "CRC-16 init 0x3692 klopt niet meer"

    # --- 2. Golden vectors, beide richtingen ---
    for hexs, snd, rcv, seq, ct, cs, ci, pl in GOLDEN:
        raw = bytes.fromhex(hexs)
        f = parse_frame(raw)
        assert (f.sender, f.receiver, f.seq) == (snd, rcv, seq), \
            "parse-mismatch adres/seq in %s" % hexs
        assert (f.cmd_type, f.cmd_set, f.cmd_id) == (ct, cs, ci), \
            "parse-mismatch cmd in %s" % hexs
        assert f.payload.hex() == pl, "parse-mismatch payload in %s" % hexs
        assert f.version == 1, "echte frames zijn version 1, kreeg %d" % f.version
        rebuilt = Frame(cmd_set=cs, cmd_id=ci, payload=bytes.fromhex(pl),
                        sender=snd, receiver=rcv, seq=seq, cmd_type=ct).build()
        assert rebuilt == raw, ("build-mismatch:\n  onze  %s\n  echte %s"
                                % (rebuilt.hex(), hexs))
    print("golden vectors OK  (%d echte DJI-frames, parse + build byte-exact)" % len(GOLDEN))

    # --- 3. cmd_type-bits (byte 8) ---
    assert cmd_type(PKT_REQUEST, ACK_AFTER, ENC_NONE) == 0x40
    assert cmd_type(PKT_RESPONSE, ACK_AFTER, ENC_NONE) == 0xC0
    assert cmd_type(PKT_REQUEST, ACK_AFTER, ENC_AES256) == 0x47
    f = Frame(cmd_set=0, cmd_id=1, cmd_type=0xC7)
    assert (f.pack_type, f.ack_type, f.encrypt_type, f.is_response) == (1, 2, 7, True)

    # --- 4. round-trip + reassembly over gefragmenteerde chunks met ruis ---
    f = Frame(cmd_set=0x00, cmd_id=0x0e, payload=b"hello-dji", seq=0x0102)
    raw = f.build()
    g = parse_frame(raw)
    assert g.cmd_set == 0x00 and g.cmd_id == 0x0e and g.payload == b"hello-dji"
    assert g.seq == 0x0102 and g.sender == ADDR_APP and g.version == 1
    r = Reassembler()
    frames = []
    stream = b"\x00\x00" + raw + Frame(cmd_set=1, cmd_id=2, payload=b"x").build()
    for k in range(0, len(stream), 4):
        frames += r.feed(stream[k:k + 4])
    assert len(frames) == 2, "verwacht 2 frames, kreeg %d" % len(frames)

    # --- 5. de 10-bits length grens: een frame >255B moet nog steeds reassemblen.
    #        Dit ving de oude 13/3-split niet, en faalt dan pas in productie. ---
    big = Frame(cmd_set=0x00, cmd_id=0x0e, payload=b"A" * 300, seq=7).build()
    assert len(big) == 313 and big[1] == 313 & 0xFF and (big[2] & 0x03) == 1
    r = Reassembler()
    got = []
    for k in range(0, len(big), 20):
        got += r.feed(big[k:k + 20])
    assert len(got) == 1 and got[0].payload == b"A" * 300, "reassembly faalt >255B"

    print("self_test OK  frame=%s bytes  version=%d" % (len(raw), g.version))
    print("hex:", raw.hex())


if __name__ == "__main__":
    self_test()
