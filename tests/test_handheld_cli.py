import importlib.util
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

ROOT = Path(__file__).resolve().parents[1]


def load_module():
    module_path = ROOT / "scripts" / "handheld_scan_display.py"
    spec = importlib.util.spec_from_file_location("handheld_scan_display", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def install_stubs():
    if "evdev" not in sys.modules:
        class DummyInputDevice:
            def __init__(self, path):
                self.path = path
                self.name = "dummy"

            def read_one(self):
                return None

            def grab(self):
                pass

            def ungrab(self):
                pass

            def close(self):
                pass

        evdev_stub = types.SimpleNamespace(
            InputDevice=DummyInputDevice,
            categorize=lambda event: event,
            ecodes=types.SimpleNamespace(EV_KEY=0),
        )
        sys.modules["evdev"] = evdev_stub

    if "waveshare_epd" not in sys.modules:
        class DummyEPD:
            def __init__(self):
                self.height = 122
                self.width = 250

            def init(self):
                pass

            def displayPartBaseImage(self, *_):
                pass

            def getbuffer(self, image):
                return image

            def display(self, *_):
                pass

            def displayPartial(self, *_):
                pass

            def sleep(self):
                pass

        waveshare_stub = types.SimpleNamespace(EPD=DummyEPD)
        sys.modules["waveshare_epd"] = types.SimpleNamespace(epd2in13_V4=waveshare_stub)
        sys.modules["waveshare_epaper"] = types.SimpleNamespace(epd2in13_V4=waveshare_stub)


install_stubs()
hsd = load_module()


def test_load_config_override(tmp_path):
    config_path = tmp_path / "config.json"
    config = {"api_url": "http://example.com", "api_token": "token", "device_id": "dev"}
    config_path.write_text(json.dumps(config))
    loaded = hsd.load_config(str(config_path))
    assert loaded == config


def test_main_drain_only(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    db_path = tmp_path / "queue.db"
    config = {
        "api_url": "http://example.com",
        "api_token": "token",
        "device_id": "dev",
        "queue_db_path": str(db_path),
    }
    config_path.write_text(json.dumps(config))

    transmitter = hsd.ScanTransmitter(config)
    transmitter.enqueue(
        "http://example.com",
        {
            "scan_id": "test-scan",
            "device_id": "dev",
            "part_code": "PART",
            "location_code": "RACK",
            "scanned_at": "2025-01-01T00:00:00Z",
        },
    )
    transmitter.conn.close()

    calls = []

    class DummyResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_post(url, json, headers, timeout):
        calls.append((url, json))
        return DummyResponse()

    monkeypatch.setattr(hsd.requests, "post", fake_post)
    monkeypatch.setattr(hsd, "configure_logging", lambda cfg: None)
    monkeypatch.setattr(hsd.time, "sleep", lambda *_: None)

    monkeypatch.setattr(
        hsd,
        "parse_args",
        lambda: SimpleNamespace(config=str(config_path), drain_only=True),
    )

    hsd.main()

    assert calls, "Expected at least one POST"
    last_transmitter = hsd.ScanTransmitter(config)
    try:
        assert last_transmitter.queue_size() == 0
    finally:
        last_transmitter.conn.close()


def test_send_logistics_job_queue(monkeypatch, tmp_path):
    config = {
        "api_url": "http://example.com/api/v1/scans",
        "logistics_api_url": "http://example.com/api/logistics/jobs",
        "logistics_default_from": "STAGING",
        "logistics_status": "completed",
        "api_token": "token",
        "device_id": "dev",
        "queue_db_path": str(tmp_path / "queue.db"),
    }
    transmitter = hsd.ScanTransmitter(config)

    class DummyResponse:
        status_code = 500

        def raise_for_status(self):
            raise requests.HTTPError("server error")

    monkeypatch.setattr(hsd.requests, "post", lambda *args, **kwargs: DummyResponse())
    transmitter.send_logistics_job("PART-1", "DEST-1")
    assert transmitter.queue_size() == 1
    transmitter.conn.close()
