"""Real adapter/API contracts exercised only with fictitious local readings."""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services import telemetry_store
from src.clinical_intelligence.alert_ingest import vitals_from_ingest_context
from src.ingestion.real.hband_normalizer import HBandNormalizer

pytestmark = pytest.mark.critical
INGEST = {'X-API-Key': 'ht_ingest_test_key_32chars_long_token'}
READ = {'X-API-Key': 'ht_read_test_key_32chars_long_token'}


def reading(**extra):
    return dict({'patient_id': 'SIM-HBAND-R2', 'device': {'device_id': 'SIM-DEVICE-R2'},
        'heart_rate': 78, 'spo2': 97, 'skin_temp': 38.5,
        'client_reading_id': 'sim-stable-reading-r2', 'ingest_source': 'ble_sim',
        'timestamp': '2026-11-16T12:00:00Z'}, **extra)


@pytest.fixture
def client(monkeypatch, tmp_path):
    from src.ops import device_registry
    monkeypatch.setenv('GCS_STAGING_BUCKET', '')
    monkeypatch.setenv('DATABASE_URL', '')
    monkeypatch.setenv('OPERATIONAL_DATABASE_URL', '')
    monkeypatch.setenv('APP_MODE', 'secure')
    monkeypatch.setattr(device_registry, 'LOCAL_FLEET_PATH', tmp_path / 'fleet.json')
    get_settings.cache_clear()
    telemetry_store.clear_all()
    with TestClient(create_app()) as c:
        yield c
    telemetry_store.clear_all()
    get_settings.cache_clear()


def test_normalizer_preserves_source_and_stable_reading_id():
    body = HBandNormalizer().to_wearable_ingest(reading())
    assert body['client_reading_id'] == 'sim-stable-reading-r2'
    assert body['ingest_source'] == 'ble_sim'


def test_partial_spo2_keeps_bronze_and_does_not_fabricate_hr():
    rows, body = HBandNormalizer().normalize_envelope({'message_type': 'realtime_ingest', 'payload': reading(heart_rate=None)})
    assert body is None
    assert {r.metric_type.value for r in rows} == {'spo2', 'skin_temp'}


def test_ppg_alone_does_not_provide_measured_heart_rate():
    with pytest.raises(ValueError, match='MEASURED_HEART_RATE_REQUIRED'):
        HBandNormalizer().from_ppg_stream({'patient_id': 'SIM-HBAND-R2',
            'device': {'device_id': 'SIM-DEVICE-R2'}, 'green_light': [100, 110, 120, 100]})


@pytest.mark.parametrize('skin', [None, 33.0, 38.5, 40.0])
def test_skin_never_substitutes_body_temperature(skin):
    v, meta = vitals_from_ingest_context(heart_rate=78, skin_temp=skin)
    assert v.temp_c is None
    v, meta = vitals_from_ingest_context(heart_rate=78, skin_temp=skin, raw_telemetry={'body_temp_c': 38.5})
    assert v.temp_c == 38.5


def test_api_adapter_roundtrip_deduplicates_without_changing_reading(client):
    body = HBandNormalizer().to_wearable_ingest(reading())
    first = client.post('/api/v1/wearables/ingest', headers=INGEST, json=body)
    assert first.status_code == 200, first.text
    a = first.json()
    assert a['ingest_status'] == 'accepted'
    second = client.post('/api/v1/wearables/ingest', headers=INGEST, json=body)
    assert second.status_code == 200
    b = second.json()
    assert b['ingest_status'] == 'duplicate'
    assert a['reading_id'] == b['reading_id']
    assert a['clinical_alerts']['vitals_used']['temp_c'] is None
    assert a['clinical_alerts']['is_true_alert'] is False
    history = client.get('/api/v1/wearables/patient/SIM-HBAND-R2/history', headers=READ)
    assert history.status_code == 200 and history.json()['total_records'] == 1


def test_explicit_body_temperature_survives_normalizer(client):
    body = HBandNormalizer().to_wearable_ingest(reading(body_temp_c=38.5, skin_temp=33.0))
    assert body['body_temp_c'] == 38.5
    out = client.post('/api/v1/wearables/ingest', headers=INGEST, json=body)
    assert out.status_code == 200
    assert out.json()['clinical_alerts']['vitals_used']['temp_c'] == 38.5


def test_missing_hr_api_remains_422(client):
    out = client.post('/api/v1/wearables/ingest', headers=INGEST, json={'patient_id': 'SIM-HBAND-R2', 'spo2': 97})
    assert out.status_code == 422


@pytest.mark.parametrize('value', ['not-a-time', '2026-11-16T12:00:00'])
def test_normalizer_rejects_invalid_or_ambiguous_measurement_time(value):
    with pytest.raises(ValueError, match='TIMESTAMP_REQUIRED|TIMEZONE_REQUIRED'):
        HBandNormalizer().to_wearable_ingest(reading(timestamp=value))


def test_timestamp_is_canonical_and_missing_time_is_not_fabricated():
    n = HBandNormalizer()
    a = n.to_wearable_ingest(reading(timestamp='2026-11-16T09:00:00-03:00'))
    b = n.to_wearable_ingest(reading())
    assert a['timestamp'] == b['timestamp']
    missing = n.to_wearable_ingest(reading(timestamp=None))
    assert 'timestamp' not in missing
    assert missing['client_reading_id'] == 'sim-stable-reading-r2'
