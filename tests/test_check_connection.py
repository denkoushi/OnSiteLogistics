import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_connection.sh"


def run_script(*args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def test_check_connection_dry_run(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "api_url": "http://example.com/api",
                "api_token": "dummy",
                "device_id": "test",
            }
        )
    )

    result = run_script("--config", str(config), "--dry-run")
    assert result.returncode == 0
    assert "Dry run" in result.stdout
    assert "API URL" in result.stdout


def test_check_connection_missing_url(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"api_token": "dummy"}))

    result = run_script("--config", str(config), "--dry-run")
    assert result.returncode != 0
    assert "api_url not set" in result.stderr
