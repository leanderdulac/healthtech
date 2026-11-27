"""R8 — cifra de campos em repouso. Só identificadores sintéticos."""

from __future__ import annotations

import base64
import importlib.util
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
SECURE = ROOT / "saude_responsiva_secure"
if str(SECURE) not in sys.path:
    sys.path.insert(0, str(SECURE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("AUTH_DISABLED", "false")
os.environ.setdefault("APP_MODE", "secure")
os.environ.setdefault("SECRET_SALT", "test-salt-not-for-production-use-32c")

from app.config import get_settings  # noqa: E402
from app.security import field_crypto  # noqa: E402
from app.security.field_backfill import (  # noqa: E402
    _enrollment_update,
    backfill_enrollments,
    backfill_last_vitals,
    backfill_overrides,
    backfill_wearable_readings,
    commit_work,
)
from app.security.field_crypto import FieldCryptoError  # noqa: E402
from app.services import durable_readings  # noqa: E402
from src.ops.device_patient_overrides import (  # noqa: E402
    get_override,
    upsert_override,
)
from src.ops.operational_patients import (  # noqa: E402
    _row_to_patient,
    ensure_database_sslmode,
    get_patient,
    set_engine,
)
from tests.support_wearable_db import (  # noqa: E402
    activate_engine,
    deactivate_engine,
    make_sqlite_engine,
)

INGEST_KEY = "ht_ingest_test_key_32chars_long_token"
SCRIPT = ROOT / "scripts" / "backfill_field_encryption.py"


def _raw_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture
def encryption_on(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", _raw_key())
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v1")
    monkeypatch.setenv("FIELD_BLIND_INDEX_KEY", _raw_key())
    monkeypatch.delenv("FIELD_ENCRYPTION_KEYS", raising=False)
    monkeypatch.delenv("FIELD_ENCRYPTION_KMS_KEY", raising=False)
    field_crypto.reset_cache()
    yield
    field_crypto.reset_cache()


def test_roundtrip_tamper_and_legacy_plaintext():
    field_crypto.reset_cache()
    assert field_crypto.is_enabled() is False
    assert field_crypto.protect("PAT-SYN-001", aad="patient_id") == "PAT-SYN-001"
    assert field_crypto.open_field("PAT-SYN-001", aad="patient_id") == "PAT-SYN-001"
    opened = field_crypto.open_json_value(
        {"heart_rate_bpm": 80}, aad="wearable.frame"
    )
    assert opened == {"heart_rate_bpm": 80}


def test_encrypt_decrypt_and_wrong_aad(encryption_on):
    token = field_crypto.protect("valor-sintetico", aad="enrollment.display_name")
    assert token.startswith("enc1:v1:")
    assert field_crypto.open_field(token, aad="enrollment.display_name") == "valor-sintetico"
    with pytest.raises(FieldCryptoError):
        field_crypto.open_field(token, aad="enrollment.phone")
    # idempotente: não embrulha um token de novo
    assert field_crypto.protect(token, aad="enrollment.display_name") == token


def test_tampered_ciphertext_is_rejected(encryption_on):
    token = field_crypto.protect("80.0", aad="vitals.spo2")
    prefix, kid, nonce, ct = token.split(":")
    flipped = ("A" if ct[0] != "A" else "B") + ct[1:]
    with pytest.raises(FieldCryptoError):
        field_crypto.open_field(f"{prefix}:{kid}:{nonce}:{flipped}", aad="vitals.spo2")


def test_key_rotation_decrypts_old_and_seals_with_new(monkeypatch):
    key_v1 = _raw_key()
    key_v2 = _raw_key()
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("FIELD_BLIND_INDEX_KEY", _raw_key())
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", key_v1)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v1")
    monkeypatch.delenv("FIELD_ENCRYPTION_KEYS", raising=False)
    field_crypto.reset_cache()
    old = field_crypto.protect("leitura-sintetica", aad="wearable.frame")
    assert old.startswith("enc1:v1:")

    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", key_v2)
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v2")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEYS", f"v1:{key_v1}")
    field_crypto.reset_cache()
    assert field_crypto.open_field(old, aad="wearable.frame") == "leitura-sintetica"
    fresh = field_crypto.protect("leitura-nova", aad="wearable.frame")
    assert fresh.startswith("enc1:v2:")
    assert field_crypto.open_field(fresh, aad="wearable.frame") == "leitura-nova"
    field_crypto.reset_cache()


def test_blind_index_is_deterministic_and_context_separated(encryption_on):
    first = field_crypto.blind_index("PAT-SYN-009", context="patient_id")
    second = field_crypto.blind_index("PAT-SYN-009", context="patient_id")
    other = field_crypto.blind_index("PAT-SYN-009", context="device_id")
    assert first == second
    assert first.startswith("bi1.")
    assert first != other
    assert "PAT-SYN-009" not in first


def test_production_requires_separate_blind_index_key(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", _raw_key())
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v1")
    monkeypatch.delenv("FIELD_BLIND_INDEX_KEY", raising=False)
    field_crypto.reset_cache()
    with pytest.raises(FieldCryptoError):
        field_crypto.is_enabled()
    field_crypto.reset_cache()


def test_kms_unwrap_hook_supplies_the_dek(monkeypatch):
    dek = os.urandom(32)
    seen = {}

    def _unwrap(wrapped: str, key_name: str) -> bytes:
        seen["wrapped"] = wrapped
        seen["key_name"] = key_name
        return dek

    field_crypto.set_kms_unwrap_for_tests(_unwrap)
    try:
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("FIELD_BLIND_INDEX_KEY", _raw_key())
        monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "d3JhcHBlZC1kZWs")
        monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v1")
        monkeypatch.setenv(
            "FIELD_ENCRYPTION_KMS_KEY",
            "projects/healthtech-gcp-2026/locations/us-central1/keyRings/healthtech/cryptoKeys/field-dek",
        )
        field_crypto.reset_cache()
        token = field_crypto.protect("via-kms", aad="t")
        assert field_crypto.open_field(token, aad="t") == "via-kms"
        assert seen["wrapped"] == "d3JhcHBlZC1kZWs"
        assert seen["key_name"].endswith("/cryptoKeys/field-dek")
    finally:
        field_crypto.set_kms_unwrap_for_tests(None)
        field_crypto.reset_cache()


def test_sslmode_require_on_remote_and_keeps_verify_full():
    remote = ensure_database_sslmode(
        "postgresql://healthtech_app:SENHA@10.8.0.4:5432/healthtech"
    )
    assert "sslmode=require" in remote
    assert "SENHA" in remote
    upgraded = ensure_database_sslmode(
        "postgresql://healthtech_app:SENHA@10.8.0.4:5432/healthtech?sslmode=disable"
    )
    assert "sslmode=require" in upgraded
    assert "sslmode=disable" not in upgraded
    verify = "postgresql://healthtech_app:SENHA@10.8.0.4:5432/healthtech?sslmode=verify-full"
    assert ensure_database_sslmode(verify) == verify
    local = "postgresql://wearable_test:wearable_test@127.0.0.1:5432/wearable_test"
    assert ensure_database_sslmode(local) == local
    socket = (
        "postgresql://healthtech_app:SENHA@/healthtech"
        "?host=/cloudsql/healthtech-gcp-2026:us-central1:healthtech-pg"
    )
    assert ensure_database_sslmode(socket) == socket
    assert ensure_database_sslmode("sqlite:///tmp/local.db") == "sqlite:///tmp/local.db"


def test_hsts_on_secure_api():
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    hsts = response.headers.get("strict-transport-security", "")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
    get_settings.cache_clear()


def _reading(patient_id: str, device_id: str, client_reading_id: str, heart_rate: float):
    return {
        "patient_id": patient_id,
        "device_id": device_id,
        "timestamp": "2026-11-25T12:00:00.000Z",
        "received_at": "2026-11-25T12:00:01.000Z",
        "client_reading_id": client_reading_id,
        "metric_type": "heart_rate",
        "raw_telemetry": {"heart_rate_bpm": heart_rate, "spo2_percent": 97.0},
        "cleaned_telemetry": {"heart_rate_clean": heart_rate},
    }


def test_legacy_row_stays_readable_and_new_row_is_sealed(tmp_path, monkeypatch):
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("FIELD_BLIND_INDEX_KEY", raising=False)
    field_crypto.reset_cache()
    engine = make_sqlite_engine(tmp_path / "r8.db")
    previous = activate_engine(engine)
    try:
        legacy, status = durable_readings.upsert_reading(
            "PAT-R8-LEGACY",
            _reading("PAT-R8-LEGACY", "DEV-SYN-01", "cid-legacy", 77.0),
            client_reading_id="cid-legacy",
            measured_at="2026-11-25T12:00:00Z",
            metric_type="heart_rate",
            extra={"heart_rate": 77.0},
        )
        assert status == "accepted"
        assert legacy["patient_id"] == "PAT-R8-LEGACY"
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT patient_id, value, frame FROM wearable_readings "
                    "WHERE client_reading_id = 'cid-legacy'"
                )
            ).fetchone()
        assert row[0] == "PAT-R8-LEGACY"
        assert row[1] == 77.0
        assert "heart_rate" in str(row[2])

        monkeypatch.setenv("FIELD_ENCRYPTION_KEY", _raw_key())
        monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v1")
        monkeypatch.setenv("FIELD_BLIND_INDEX_KEY", _raw_key())
        monkeypatch.setenv("ENVIRONMENT", "development")
        field_crypto.reset_cache()

        still = durable_readings.get_latest("PAT-R8-LEGACY")
        assert still is not None
        assert still["patient_id"] == "PAT-R8-LEGACY"
        assert still["raw_telemetry"]["heart_rate_bpm"] == 77.0

        again, again_status = durable_readings.upsert_reading(
            "PAT-R8-LEGACY",
            _reading("PAT-R8-LEGACY", "DEV-SYN-01", "cid-legacy", 77.0),
            client_reading_id="cid-legacy",
            measured_at="2026-11-25T12:00:00Z",
            metric_type="heart_rate",
            extra={"heart_rate": 77.0},
        )
        assert again_status == "duplicate"
        assert again["patient_id"] == "PAT-R8-LEGACY"

        fresh, fresh_status = durable_readings.upsert_reading(
            "PAT-R8-NEW",
            _reading("PAT-R8-NEW", "AA:BB:CC:DD:EE:10", "cid-new", 81.0),
            client_reading_id="cid-new",
            measured_at="2026-11-25T12:05:00Z",
            metric_type="heart_rate",
            extra={"heart_rate": 81.0},
        )
        assert fresh_status == "accepted"
        assert fresh["patient_id"] == "PAT-R8-NEW"
        assert fresh["device_id"] == "AA:BB:CC:DD:EE:10"
        assert fresh["cleaned_telemetry"]["heart_rate_clean"] == 81.0

        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT patient_id, device_id, value, frame FROM wearable_readings "
                    "WHERE client_reading_id = 'cid-new'"
                )
            ).fetchone()
        assert str(stored[0]).startswith("bi1.")
        assert stored[0] != "PAT-R8-NEW"
        assert str(stored[1]).startswith("bi1.")
        assert "AA:BB:CC:DD:EE:10" not in str(stored[1])
        assert stored[2] is None
        blob = stored[3] if isinstance(stored[3], str) else json.dumps(stored[3])
        assert "_enc" in blob
        assert "heart_rate" not in blob
        assert "PAT-R8-NEW" not in blob

        loaded = durable_readings.get_latest("PAT-R8-NEW")
        assert loaded is not None
        assert loaded["patient_id"] == "PAT-R8-NEW"
        assert loaded["raw_telemetry"]["heart_rate_bpm"] == 81.0

        preview = backfill_wearable_readings(engine, dry_run=True)
        assert preview["updated"] >= 1
        with engine.connect() as conn:
            untouched = conn.execute(
                text(
                    "SELECT patient_id FROM wearable_readings "
                    "WHERE client_reading_id = 'cid-legacy'"
                )
            ).fetchone()
        assert untouched[0] == "PAT-R8-LEGACY"

        first = backfill_wearable_readings(engine)
        assert first["updated"] >= 1
        second = backfill_wearable_readings(engine)
        assert second["updated"] == 0
        assert second["skipped"] == second["scanned"]
        after = durable_readings.get_history("PAT-R8-LEGACY", limit=5)
        assert after and after[-1]["patient_id"] == "PAT-R8-LEGACY"

        rolled = backfill_wearable_readings(engine, decrypt=True)
        assert rolled["updated"] >= 1
        with engine.connect() as conn:
            plain = conn.execute(
                text(
                    "SELECT patient_id FROM wearable_readings "
                    "WHERE client_reading_id = 'cid-legacy'"
                )
            ).fetchone()
        assert plain[0] == "PAT-R8-LEGACY"
        again_plain = backfill_wearable_readings(engine, decrypt=True)
        assert again_plain["updated"] == 0
    finally:
        deactivate_engine(engine, restore=previous)
        field_crypto.reset_cache()


@pytest.mark.critical
def test_batch_ingest_contract_with_encryption(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", _raw_key())
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v1")
    monkeypatch.setenv("FIELD_BLIND_INDEX_KEY", _raw_key())
    field_crypto.reset_cache()
    engine = make_sqlite_engine(tmp_path / "batch.db")
    previous = activate_engine(engine)
    try:
        get_settings.cache_clear()
        from app.main import create_app

        batch = {
            "patient_id": "PAT-R8-BATCH",
            "readings": [
                {
                    "patient_id": "PAT-R8-BATCH",
                    "device_id": "DEV-SYN-02",
                    "heart_rate": 76.0,
                    "timestamp": "2026-11-25T13:00:00Z",
                    "client_reading_id": "batch-a",
                },
                {
                    "patient_id": "PAT-R8-BATCH",
                    "device_id": "DEV-SYN-02",
                    "heart_rate": 76.0,
                    "timestamp": "2026-11-25T13:00:00Z",
                    "client_reading_id": "batch-a",
                },
            ],
        }
        with TestClient(create_app()) as client:
            response = client.post(
                "/api/v1/wearables/batch-ingest",
                headers={"X-API-Key": INGEST_KEY},
                json=batch,
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["patient_id"] == "PAT-R8-BATCH"
        assert body["accepted_count"] == 1
        assert body["duplicate_count"] == 1
        assert body["rejected_count"] == 0
        assert body["results"][0]["status"] == "accepted"
        result = body["results"][0]["result"]
        assert result["patient_id"] == "PAT-R8-BATCH"
        assert result["cleaned_telemetry"]["heart_rate_clean"] == 76.0
        assert "bi1." not in json.dumps(body)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT patient_id, frame FROM wearable_readings")
            ).fetchone()
        assert str(row[0]).startswith("bi1.")
        blob = row[1] if isinstance(row[1], str) else json.dumps(row[1])
        assert "_enc" in blob
        assert "PAT-R8-BATCH" not in blob
    finally:
        deactivate_engine(engine, restore=previous)
        field_crypto.reset_cache()
        get_settings.cache_clear()


def test_enrollment_backfill_and_read(tmp_path, encryption_on):
    engine = make_sqlite_engine(tmp_path / "enroll.db")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE enrollments (
                    patient_id TEXT PRIMARY KEY,
                    display_name TEXT,
                    phone TEXT,
                    caregiver_phone TEXT,
                    programs TEXT,
                    diseases TEXT,
                    isolation_social INTEGER DEFAULT 0,
                    is_demo INTEGER DEFAULT 1,
                    municipality_id TEXT,
                    ubs_id TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO enrollments "
                "(patient_id, display_name, phone, diseases, is_demo) "
                "VALUES (:pid, :name, :phone, :diseases, 1)"
            ),
            {
                "pid": "PAT-R8-CAD",
                "name": "Pessoa sintetica",
                "phone": "5500000000000",
                "diseases": "[\"hipertensao\"]",
            },
        )
    set_engine(engine)
    try:
        first = backfill_enrollments(engine)
        assert first["updated"] == 1
        with engine.connect() as conn:
            raw = conn.execute(
                text("SELECT display_name, phone, diseases FROM enrollments")
            ).fetchone()
        assert str(raw[0]).startswith("enc1:")
        assert str(raw[1]).startswith("enc1:")
        assert "Pessoa sintetica" not in str(raw[0])
        assert "5500000000000" not in str(raw[1])
        patient = get_patient("PAT-R8-CAD")
        assert patient is not None
        assert patient["display_name"] == "Pessoa sintetica"
        assert patient["phone"] == "5500000000000"
        assert patient["diseases"] == ["hipertensao"]
        second = backfill_enrollments(engine)
        assert second["updated"] == 0
        assert second["skipped"] == 1
        rolled = backfill_enrollments(engine, decrypt=True)
        assert rolled["updated"] == 1
        with engine.connect() as conn:
            plain = conn.execute(text("SELECT display_name FROM enrollments")).fetchone()
        assert plain[0] == "Pessoa sintetica"
    finally:
        from src.ops.operational_patients import reset_engine

        reset_engine()


def test_last_vitals_and_override_use_enc_columns_when_present(tmp_path, encryption_on):
    engine = make_sqlite_engine(tmp_path / "vitals.db")
    previous = activate_engine(engine)
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE wearable_device_last_vitals ADD COLUMN spo2_enc TEXT"))
            conn.execute(text("ALTER TABLE wearable_device_last_vitals ADD COLUMN steps_enc TEXT"))
            conn.execute(
                text(
                    "ALTER TABLE wearable_device_last_vitals "
                    "ADD COLUMN blood_pressure_sys_enc TEXT"
                )
            )
            conn.execute(
                text(
                    "ALTER TABLE wearable_device_last_vitals "
                    "ADD COLUMN blood_pressure_dia_enc TEXT"
                )
            )
            conn.execute(
                text("ALTER TABLE device_patient_overrides ADD COLUMN device_id_enc TEXT")
            )
            conn.execute(
                text("ALTER TABLE device_patient_overrides ADD COLUMN patient_id_enc TEXT")
            )
        frame = _reading("PAT-R8-VIT", "DEV-SYN-03", "cid-vit", 70.0)
        frame["raw_telemetry"]["spo2_percent"] = 98.0
        durable_readings.upsert_reading(
            "PAT-R8-VIT",
            frame,
            client_reading_id="cid-vit",
            measured_at="2026-11-25T14:00:00Z",
            metric_type="heart_rate",
            extra={"heart_rate": 70.0, "spo2": 98.0},
        )
        with engine.connect() as conn:
            vital = conn.execute(
                text("SELECT spo2, spo2_enc FROM wearable_device_last_vitals")
            ).fetchone()
        assert vital[0] is None
        assert str(vital[1]).startswith("enc1:")
        listed = durable_readings.list_device_last_vitals()
        assert listed["DEV-SYN-03"]["spo2"] == 98.0

        saved = upsert_override(
            device_id="AA:BB:CC:DD:EE:22",
            patient_id="PAT-R8-OVR",
            created_by="teste",
            motivo="vinculo sintetico",
        )
        assert saved["device_id"] == "AA:BB:CC:DD:EE:22"
        assert saved["patient_id"] == "PAT-R8-OVR"
        with engine.connect() as conn:
            raw = conn.execute(
                text(
                    "SELECT device_id, patient_id, device_id_enc "
                    "FROM device_patient_overrides WHERE motivo = 'vinculo sintetico'"
                )
            ).fetchone()
            panel = conn.execute(
                text(
                    "SELECT patient_id FROM device_patient_overrides "
                    "WHERE device_id = 'AA:BB:CC:DD:EE:22'"
                )
            ).fetchone()
        assert raw[0] == "AA:BB:CC:DD:EE:22"
        assert raw[1] == "PAT-R8-OVR"
        assert raw[2] is None
        assert panel[0] == "PAT-R8-OVR"
        loaded = get_override("aa:bb:cc:dd:ee:22")
        assert loaded is not None
        assert loaded["device_id"] == "AA:BB:CC:DD:EE:22"
        assert loaded["patient_id"] == "PAT-R8-OVR"

        from app.security.field_crypto import blind_index, seal_text

        legacy_mac = "AA:BB:CC:DD:EE:44"
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO device_patient_overrides ("
                    "device_id, patient_id, created_by, created_at, updated_at, motivo, "
                    "device_id_enc, patient_id_enc"
                    ") VALUES ("
                    ":device_id, :patient_id, 'teste', "
                    "'2026-11-25T00:00:00Z', '2026-11-25T00:00:00Z', 'legado', "
                    ":device_id_enc, :patient_id_enc)"
                ),
                {
                    "device_id": blind_index(legacy_mac, context="device_id"),
                    "patient_id": blind_index("PAT-R8-OLD", context="patient_id"),
                    "device_id_enc": seal_text(legacy_mac, aad="override.device_id"),
                    "patient_id_enc": seal_text("PAT-R8-OLD", aad="override.patient_id"),
                },
            )
            hidden = conn.execute(
                text(
                    "SELECT patient_id FROM device_patient_overrides "
                    "WHERE device_id = :mac"
                ),
                {"mac": legacy_mac},
            ).fetchone()
        assert hidden is None
        opened = get_override(legacy_mac.lower())
        assert opened is not None
        assert opened["patient_id"] == "PAT-R8-OLD"
        restored = backfill_overrides(engine, batch_size=1)
        assert restored["updated"] == 1
        with engine.connect() as conn:
            visible = conn.execute(
                text(
                    "SELECT device_id, patient_id, device_id_enc, patient_id_enc "
                    "FROM device_patient_overrides WHERE motivo = 'legado'"
                )
            ).fetchone()
        assert visible[0] == legacy_mac
        assert visible[1] == "PAT-R8-OLD"
        assert visible[2] is None
        assert visible[3] is None
        again = backfill_overrides(engine)
        assert again["updated"] == 0

        vitals_pass = backfill_last_vitals(engine)
        assert vitals_pass["updated"] == 0
        assert vitals_pass["skipped"] == 1
    finally:
        deactivate_engine(engine, restore=previous)


def test_backfill_cli_refuses_without_explicit_confirm():
    env = os.environ.copy()
    env.pop("BACKFILL_FIELD_ENCRYPTION_CONFIRM", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "BACKFILL_FIELD_ENCRYPTION_CONFIRM" in result.stderr
    assert "FIELD_ENCRYPTION_KEY=" not in result.stderr


def _load_backfill_cli():
    spec = importlib.util.spec_from_file_location("backfill_cli_r8", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_flag_stays_separate_from_backfill():
    module = _load_backfill_cli()

    def args(**kwargs):
        base = {"apply_schema": False, "backfill": False, "decrypt": False, "dry_run": False}
        base.update(kwargs)
        return SimpleNamespace(**base)

    assert module.selected_actions(args()) == (False, True)
    assert module.selected_actions(args(apply_schema=True)) == (True, False)
    assert module.selected_actions(args(backfill=True)) == (False, True)
    assert module.selected_actions(args(apply_schema=True, backfill=True)) == (True, True)
    assert module.selected_actions(args(apply_schema=True, dry_run=True)) == (False, True)
    assert module.selected_actions(args(decrypt=True)) == (False, True)


def test_apply_schema_main_does_not_rewrite_rows(monkeypatch):
    module = _load_backfill_cli()
    monkeypatch.setenv("BACKFILL_FIELD_ENCRYPTION_CONFIRM", "yes")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:senha@127.0.0.1:9/none")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", _raw_key())
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v1")
    monkeypatch.setenv("FIELD_BLIND_INDEX_KEY", _raw_key())
    field_crypto.reset_cache()
    called = {"schema": 0, "rows": 0}
    monkeypatch.setattr(module, "_apply_schema", lambda engine: called.__setitem__("schema", 1))
    monkeypatch.setattr(
        "app.services.durable_readings.database_url",
        lambda: "postgresql://user:senha@127.0.0.1:9/none",
    )
    monkeypatch.setattr("app.services.durable_readings.get_engine", lambda: object())
    monkeypatch.setattr(
        "app.services.durable_readings.redact_database_url", lambda url: "redacted"
    )

    def rows(*_args, **_kwargs):
        called["rows"] += 1
        return {"scanned": 0, "updated": 0, "skipped": 0, "batches": 0}

    monkeypatch.setattr("app.security.field_backfill.backfill_wearable_readings", rows)
    monkeypatch.setattr("app.security.field_backfill.backfill_enrollments", rows)
    monkeypatch.setattr("app.security.field_backfill.backfill_last_vitals", rows)
    monkeypatch.setattr("app.security.field_backfill.backfill_overrides", rows)
    try:
        assert module.main(["--apply-schema"]) == 0
        assert called == {"schema": 1, "rows": 0}
        assert module.main(["--backfill", "--batch-size", "500"]) == 0
        assert called["schema"] == 1
        assert called["rows"] == 4
    finally:
        field_crypto.reset_cache()


def test_backfill_commits_each_batch_and_resumes(tmp_path, encryption_on):
    engine = make_sqlite_engine(tmp_path / "batches.db")
    durable_readings.apply_schema(engine)

    def insert(reading_id: str, patient: str) -> None:
        frame = json.dumps(
            {
                "patient_id": patient,
                "device_id": "DEV-SYN-BATCH",
                "metric_type": "heart_rate",
                "raw_telemetry": {"heart_rate_bpm": 70},
            }
        )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO wearable_readings ("
                    "reading_id, patient_id, device_id, metric_type, value, unit, "
                    "received_at, extra, frame, created_at"
                    ") VALUES ("
                    ":reading_id, :patient_id, 'DEV-SYN-BATCH', 'heart_rate', 70, 'bpm', "
                    "'2026-11-25T12:00:00', :extra, :frame, '2026-11-25T12:00:00')"
                ),
                {
                    "reading_id": reading_id,
                    "patient_id": patient,
                    "extra": json.dumps({"heart_rate": 70}),
                    "frame": frame,
                },
            )

    insert("r1", "PAT-R8-B1")
    insert("r2", "PAT-R8-B2")
    insert("r3", "PAT-R8-B3")
    seen = []

    def on_batch(_stats):
        with engine.connect() as conn:
            seen.append(
                conn.execute(
                    text("SELECT COUNT(*) FROM wearable_readings WHERE patient_id LIKE 'bi1.%'")
                ).scalar()
            )

    class _Stop(RuntimeError):
        pass

    def stop_early(stats):
        on_batch(stats)
        if stats["batches"] >= 1:
            raise _Stop()

    with pytest.raises(_Stop):
        backfill_wearable_readings(engine, batch_size=1, on_batch=stop_early)
    assert seen == [1]
    rest = backfill_wearable_readings(engine, batch_size=1, on_batch=on_batch)
    assert rest["updated"] == 2
    assert rest["skipped"] == 1
    assert rest["batches"] == 2
    assert seen == [1, 2, 3]
    second = backfill_wearable_readings(engine, batch_size=500)
    assert second["updated"] == 0
    assert second["skipped"] == 3


def test_commit_work_retries_deadlock_and_lock_timeout(tmp_path):
    engine = make_sqlite_engine(tmp_path / "retry.db")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (n INTEGER)"))
        conn.execute(text("INSERT INTO t (n) VALUES (0)"))

    for sqlstate in ("40P01", "55P03"):
        with engine.begin() as conn:
            conn.execute(text("UPDATE t SET n = 0"))
        state = {"n": 0}
        delays = []

        def work(conn, _sqlstate=sqlstate):
            state["n"] += 1
            if state["n"] < 3:
                err = SQLAlchemyError("lock")
                err.orig = SimpleNamespace(pgcode=_sqlstate)
                raise err
            conn.execute(text("UPDATE t SET n = 1"))

        commit_work(engine, "sqlite", work, sleeper=delays.append)
        assert state["n"] == 3
        assert delays == [0.5, 1.0]
        with engine.connect() as conn:
            assert conn.execute(text("SELECT n FROM t")).scalar() == 1

    state = {"n": 0}

    def other(conn):
        state["n"] += 1
        err = SQLAlchemyError("unique")
        err.orig = SimpleNamespace(pgcode="23505")
        raise err

    with pytest.raises(FieldCryptoError, match="23505"):
        commit_work(engine, "sqlite", other, sleeper=lambda _delay: None)
    assert state["n"] == 1


def test_boot_migration_skips_ddl_that_already_exists(tmp_path):
    engine = make_sqlite_engine(tmp_path / "ddl.db")
    durable_readings.apply_schema(engine)
    durable_readings.apply_schema(engine)
    with engine.connect() as conn:
        assert durable_readings.migration_statement_skippable(
            conn,
            "ALTER TABLE wearable_readings ADD COLUMN IF NOT EXISTS device_label TEXT",
        )
        assert not durable_readings.migration_statement_skippable(
            conn,
            "ALTER TABLE wearable_readings ADD COLUMN IF NOT EXISTS ainda_nao TEXT",
        )
        assert durable_readings.migration_statement_skippable(
            conn,
            "CREATE INDEX IF NOT EXISTS ix_wearable_readings_patient_time "
            "ON wearable_readings (patient_id, received_at DESC)",
        )
        assert durable_readings.migration_statement_skippable(
            conn,
            "CREATE TABLE IF NOT EXISTS wearable_readings (reading_id TEXT PRIMARY KEY)",
        )
        assert not durable_readings.migration_statement_skippable(
            conn,
            "COMMENT ON COLUMN wearable_readings.device_label IS 'rotulo'",
        )
    source = inspect.getsource(durable_readings.apply_schema)
    assert "SET LOCAL lock_timeout" in source
    assert "migration_statement_skippable" in source


def test_diseases_text_array_encrypts_each_element(encryption_on):
    plain = ["hipertensao", "diabetes"]
    mixed_token = field_crypto.protect("diabetes", aad="enrollment.diseases")
    first = _enrollment_update(
        {
            "patient_id": "PAT-R8-ARR",
            "display_name": "Pessoa sintetica",
            "phone": None,
            "caregiver_phone": None,
            "diseases": plain,
        },
        decrypt=False,
    )
    assert first is not None
    assert isinstance(first["diseases"], list)
    assert all(isinstance(item, str) and item.startswith("enc1:") for item in first["diseases"])
    assert not any(item.startswith("[") or item.startswith("{") for item in first["diseases"])
    assert "hipertensao" not in "".join(first["diseases"])
    again = _enrollment_update(
        {
            "patient_id": "PAT-R8-ARR",
            "display_name": first["display_name"],
            "phone": None,
            "caregiver_phone": None,
            "diseases": first["diseases"],
        },
        decrypt=False,
    )
    assert again is None

    mixed = _enrollment_update(
        {
            "patient_id": "PAT-R8-ARR",
            "display_name": first["display_name"],
            "phone": None,
            "caregiver_phone": None,
            "diseases": ["hipertensao", mixed_token],
        },
        decrypt=False,
    )
    assert mixed is not None
    assert mixed["diseases"][1] == mixed_token
    assert mixed["diseases"][0].startswith("enc1:")
    assert mixed["diseases"][0] != mixed_token

    opened = _enrollment_update(
        {
            "patient_id": "PAT-R8-ARR",
            "display_name": first["display_name"],
            "phone": None,
            "caregiver_phone": None,
            "diseases": first["diseases"],
        },
        decrypt=True,
    )
    assert opened is not None
    assert opened["diseases"] == plain
    assert opened["display_name"] == "Pessoa sintetica"
    assert (
        _enrollment_update(
            {
                "patient_id": "PAT-R8-ARR",
                "display_name": "Pessoa sintetica",
                "phone": None,
                "caregiver_phone": None,
                "diseases": plain,
            },
            decrypt=True,
        )
        is None
    )

    class _Row:
        def __init__(self, **kwargs):
            self._mapping = kwargs

    legacy = _row_to_patient(_Row(patient_id="PAT-R8-ARR", diseases=plain))
    assert legacy["diseases"] == plain
    sealed = _row_to_patient(
        _Row(patient_id="PAT-R8-ARR", diseases=[mixed["diseases"][0], mixed_token])
    )
    assert sealed["diseases"] == plain


def test_backfill_enrollments_writes_text_array_not_a_single_token(encryption_on):
    state = {
        "patient_id": "PAT-R8-ARR",
        "display_name": "Pessoa sintetica",
        "phone": "5500000000000",
        "caregiver_phone": None,
        "diseases": ["hipertensao", "diabetes"],
    }
    writes = []

    class _Row:
        def __init__(self, mapping):
            self._mapping = mapping

        def __getitem__(self, index):
            return "enrollments"

    class _Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def fetchall(self):
            return self._rows

    class _Conn:
        def execute(self, statement, params=None):
            sql = " ".join(str(statement).split())
            if sql.upper().startswith("SET"):
                return _Result([])
            if "to_regclass" in sql:
                return _Result([_Row(state)])
            if sql.upper().startswith("SELECT"):
                after = (params or {}).get("after") or ""
                if after:
                    return _Result([])
                return _Result([_Row(dict(state))])
            assert sql.upper().startswith("UPDATE")
            assert isinstance(params["diseases"], list)
            writes.append(list(params["diseases"]))
            state["diseases"] = list(params["diseases"])
            state["display_name"] = params["display_name"]
            state["phone"] = params["phone"]
            state["caregiver_phone"] = params["caregiver_phone"]
            return _Result([])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Engine:
        dialect = SimpleNamespace(name="postgresql")

        def connect(self):
            return _Conn()

        def begin(self):
            return _Conn()

    engine = _Engine()
    first = backfill_enrollments(engine, batch_size=1)
    assert first["updated"] == 1
    assert first["batches"] == 1
    assert len(writes) == 1
    assert len(writes[0]) == 2
    assert all(item.startswith("enc1:") for item in writes[0])
    second = backfill_enrollments(engine, batch_size=1)
    assert second["updated"] == 0
    assert second["skipped"] == 1
    assert len(writes) == 1
    rolled = backfill_enrollments(engine, decrypt=True, batch_size=1)
    assert rolled["updated"] == 1
    assert state["diseases"] == ["hipertensao", "diabetes"]
    assert state["display_name"] == "Pessoa sintetica"
    again = backfill_enrollments(engine, decrypt=True, batch_size=1)
    assert again["updated"] == 0


def test_last_vitals_resumes_partial_row_and_decrypts(tmp_path, encryption_on):
    engine = make_sqlite_engine(tmp_path / "vitals-partial.db")
    durable_readings.apply_schema(engine)
    spo2_token = field_crypto.protect("98", aad="vitals.spo2")
    with engine.begin() as conn:
        for column in (
            "spo2_enc",
            "steps_enc",
            "blood_pressure_sys_enc",
            "blood_pressure_dia_enc",
        ):
            conn.execute(
                text(f"ALTER TABLE wearable_device_last_vitals ADD COLUMN {column} TEXT")
            )
        conn.execute(
            text(
                "INSERT INTO wearable_device_last_vitals ("
                "device_id, spo2, steps, blood_pressure_sys, blood_pressure_dia, "
                "spo2_enc, updated_at"
                ") VALUES ("
                "'DEV-SYN-V', NULL, 1200, 120, NULL, :spo2_enc, '2026-11-25T00:00:00')"
            ),
            {"spo2_enc": spo2_token},
        )
    first = backfill_last_vitals(engine, batch_size=1)
    assert first["updated"] == 1
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT spo2, spo2_enc, steps, steps_enc, blood_pressure_sys, "
                "blood_pressure_sys_enc FROM wearable_device_last_vitals"
            )
        ).fetchone()
    assert row[0] is None
    assert row[1] == spo2_token
    assert row[2] is None
    assert str(row[3]).startswith("enc1:")
    assert row[4] is None
    assert str(row[5]).startswith("enc1:")
    second = backfill_last_vitals(engine)
    assert second["updated"] == 0
    assert second["skipped"] == 1
    rolled = backfill_last_vitals(engine, decrypt=True)
    assert rolled["updated"] == 1
    with engine.connect() as conn:
        plain = conn.execute(
            text(
                "SELECT spo2, steps, blood_pressure_sys, blood_pressure_dia, "
                "spo2_enc, steps_enc FROM wearable_device_last_vitals"
            )
        ).fetchone()
    assert plain[0] == 98.0
    assert plain[1] == 1200.0
    assert plain[2] == 120.0
    assert plain[3] is None
    assert plain[4] is None
    assert plain[5] is None
    assert backfill_last_vitals(engine, decrypt=True)["updated"] == 0


def test_backfill_only_limits_tables_and_keeps_going(monkeypatch):
    module = _load_backfill_cli()
    monkeypatch.setenv("BACKFILL_FIELD_ENCRYPTION_CONFIRM", "yes")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:senha@127.0.0.1:9/none")
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", _raw_key())
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY_ID", "v1")
    monkeypatch.setenv("FIELD_BLIND_INDEX_KEY", _raw_key())
    field_crypto.reset_cache()
    monkeypatch.setattr(
        "app.services.durable_readings.database_url",
        lambda: "postgresql://user:senha@127.0.0.1:9/none",
    )
    monkeypatch.setattr("app.services.durable_readings.get_engine", lambda: object())
    monkeypatch.setattr(
        "app.services.durable_readings.redact_database_url", lambda url: "redacted"
    )
    called = []

    def ok(name):
        def _run(*_args, **_kwargs):
            called.append(name)
            if name == "enrollments":
                raise FieldCryptoError("lote interrompido (22P02)")
            return {"scanned": 0, "updated": 0, "skipped": 0, "batches": 0}

        return _run

    monkeypatch.setattr(
        "app.security.field_backfill.backfill_wearable_readings", ok("wearable_readings")
    )
    monkeypatch.setattr("app.security.field_backfill.backfill_enrollments", ok("enrollments"))
    monkeypatch.setattr("app.security.field_backfill.backfill_last_vitals", ok("last_vitals"))
    monkeypatch.setattr("app.security.field_backfill.backfill_overrides", ok("overrides"))
    try:
        assert module.main(["--backfill", "--only", "pacientes"]) == 2
        assert called == []
        assert module.main(["--backfill", "--only", "enrollments,last_vitals"]) == 1
        assert called == ["enrollments", "last_vitals"]
    finally:
        field_crypto.reset_cache()
