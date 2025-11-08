"""End-to-end smoke test for the CLI send command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from glitter.security import compute_file_sha256
from glitter.transfer import TransferService


pytestmark = pytest.mark.smoke


def _write_minimal_config(fake_home: Path) -> Path:
    config_dir = fake_home / ".glitter"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_payload = {
        "language": "en",
        "device_name": "SmokeTester",
        "device_id": "cli-smoke-device",
        "encryption_enabled": True,
        "auto_accept_trusted": "off",
    }
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(config_payload), encoding="utf-8")
    return config_file


def test_cli_send_command_smoke(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    _write_minimal_config(fake_home)

    dest_dir = tmp_path / "incoming"
    dest_dir.mkdir(parents=True, exist_ok=True)

    payload = ("Smoke test payload\n" * 4).encode("utf-8")
    src_file = tmp_path / "sample.txt"
    src_file.write_bytes(payload)
    expected_hash = compute_file_sha256(src_file)

    def on_new_request(ticket) -> None:
        ticket.accept(dest_dir)

    service = TransferService(
        device_id="receiver-id",
        device_name="receiver",
        language="en",
        on_new_request=on_new_request,
        bind_port=0,
        allow_ephemeral_fallback=False,
        encryption_enabled=True,
    )

    try:
        service.start()

        env = os.environ.copy()
        env["HOME"] = str(fake_home)
        env["USERPROFILE"] = str(fake_home)

        target = f"127.0.0.1:{service.port}"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "glitter",
                "send",
                target,
                str(src_file),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            timeout=40,
        )

        assert proc.returncode == 0, f"CLI send failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        assert "Transfer completed successfully." in (proc.stdout or ""), proc.stdout

        received = dest_dir / src_file.name
        deadline = time.time() + 5
        while not received.exists() and time.time() < deadline:
            time.sleep(0.05)

        assert received.exists(), "expected received file from CLI send"
        assert compute_file_sha256(received) == expected_hash

        history_file = fake_home / ".glitter" / "history.jsonl"
        assert history_file.exists(), "send command should log history entries"

        records = [json.loads(line) for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        matching = [entry for entry in records if entry.get("filename") == src_file.name]
        assert matching, "history should contain the sent file entry"
        latest = matching[-1]
        assert latest.get("status") == "completed"
        assert latest.get("direction") == "send"
        assert latest.get("remote_ip") == "127.0.0.1"
        assert latest.get("sha256") == expected_hash
        assert latest.get("local_device") == "SmokeTester"
        assert latest.get("source_path") == str(src_file)
    finally:
        service.stop()
