from pathlib import Path

import json


def test_config_sample_has_required_fields():
    sample_path = Path(__file__).resolve().parents[1] / "config" / "config.sample.json"
    assert sample_path.exists()

    with sample_path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    for key in ("api_url", "api_token", "device_id", "queue_db_path", "timeout_seconds", "log_dir"):
        assert key in data, f"Missing key: {key}"
        assert data[key] != "", f"Empty value for key: {key}"
