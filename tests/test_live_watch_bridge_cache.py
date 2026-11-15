"""Ponte da frota: cache curto e um único GET /devices por vez."""

from __future__ import annotations

import json
import threading
import time

from src.ops import live_watch_bridge as br


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_secure_fleet_reuses_fresh_cache(monkeypatch):
    br.reset_bridge_state()
    monkeypatch.setenv("SECURE_API_BASE_URL", "https://core.example")
    monkeypatch.setenv("SECURE_READ_API_KEY", "test-read-key")
    calls = {"n": 0}

    def fake_urlopen(req, timeout=8.0):
        calls["n"] += 1
        return _Resp({"devices": [{"device_id": "D1"}]})

    monkeypatch.setattr(br.urllib.request, "urlopen", fake_urlopen)
    first = br.fetch_secure_fleet()
    second = br.fetch_secure_fleet()
    assert first == second == [{"device_id": "D1"}]
    assert calls["n"] == 1


def test_fetch_secure_fleet_single_flight(monkeypatch):
    br.reset_bridge_state()
    monkeypatch.setenv("SECURE_API_BASE_URL", "https://core.example")
    monkeypatch.setenv("SECURE_READ_API_KEY", "test-read-key")
    calls = {"n": 0}
    started = threading.Event()
    release = threading.Event()

    def fake_urlopen(req, timeout=8.0):
        calls["n"] += 1
        started.set()
        release.wait(timeout=2.0)
        return _Resp({"devices": [{"device_id": "D2"}]})

    monkeypatch.setattr(br.urllib.request, "urlopen", fake_urlopen)
    results = []

    def worker():
        results.append(br.fetch_secure_fleet(timeout=2.0))

    first = threading.Thread(target=worker)
    second = threading.Thread(target=worker)
    first.start()
    assert started.wait(timeout=2.0)
    second.start()
    time.sleep(0.05)
    release.set()
    first.join(timeout=3.0)
    second.join(timeout=3.0)
    assert calls["n"] == 1
    assert results == [[{"device_id": "D2"}], [{"device_id": "D2"}]]
