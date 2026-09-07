"""Espelha HeartRateMeasurementParser.kt (Bluetooth SIG 0x2A37)."""


def parse_bpm(value: bytes | None) -> int | None:
    if not value:
        return None
    flags = value[0]
    hr16 = flags & 0x01 != 0
    if hr16:
        if len(value) < 3:
            return None
        bpm = value[1] | (value[2] << 8)
    else:
        if len(value) < 2:
            return None
        bpm = value[1]
    return bpm if 20 <= bpm <= 250 else None


def test_uint8_hr_not_the_flags_byte():
    # flags=0 (UINT8), BPM=78. Tratar flags como BPM daria 0 — o bug clássico.
    assert parse_bpm(bytes([0x00, 78])) == 78
    assert parse_bpm(bytes([0x00])) is None


def test_uint16_little_endian():
    assert parse_bpm(bytes([0x01, 100, 0])) == 100
    # 300 (0x012C LE) está fora de 20–250
    assert parse_bpm(bytes([0x01, 0x2C, 0x01])) is None


def test_rejects_out_of_range():
    assert parse_bpm(bytes([0x00, 5])) is None
    assert parse_bpm(bytes([0x00, 251])) is None
