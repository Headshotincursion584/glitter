"""CLI receive/settings tests exercising critical flows."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

from glitter.security import compute_file_sha256
from glitter.transfer import TransferService


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _write_config(fake_home: Path, overrides: dict | None = None) -> Path:
    config_dir = fake_home / ".glitter"
    config_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "language": "en",
        "device_name": "SmokeTester",
        "device_id": "cli-device",
        "encryption_enabled": True,
        "auto_accept_trusted": "off",
    }
    if overrides:
        payload.update(overrides)
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps(payload), encoding="utf-8")
    return config_file


def _env_for(fake_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    return env


def _wait_for_path(path: Path, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for {path}")


def test_cli_receive_requires_mode_argument(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    _write_config(fake_home)

    env = _env_for(fake_home)
    result = subprocess.run(
        [sys.executable, "-m", "glitter", "receive"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=20,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 1
    assert "Auto-accept mode is Off" in combined


def test_cli_receive_auto_accept_all_with_no_encryption(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    _write_config(fake_home)

    dest_dir = tmp_path / "receive-target"
    src_file = tmp_path / "payload.bin"
    payload = b"receive smoke payload" * 4
    src_file.write_bytes(payload)
    expected_hash = compute_file_sha256(src_file)

    port = _find_free_port()
    env = _env_for(fake_home)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "glitter",
            "receive",
            "--mode",
            "all",
            "--dir",
            str(dest_dir),
            "--port",
            str(port),
            "--no-encryption",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )

    stdout_data = ""
    stderr_data = ""
    try:
        time.sleep(1.0)

        sender = TransferService(
            device_id="sender-id",
            device_name="sender",
            language="en",
            on_new_request=lambda ticket: None,
            bind_port=0,
            allow_ephemeral_fallback=False,
            encryption_enabled=True,
        )
        sender.start()
        sender.set_encryption_enabled(False)
        try:
            deadline = time.time() + 15
            while True:
                try:
                    status, sent_hash, _ = sender.send_file(
                        target_ip="127.0.0.1",
                        target_port=port,
                        peer_name="cli",
                        file_path=src_file,
                    )
                except (OSError, ConnectionError):
                    if time.time() > deadline:
                        raise
                    time.sleep(0.2)
                    continue
                assert status == "accepted"
                assert sent_hash == expected_hash
                break
        finally:
            sender.stop()

        received = dest_dir / src_file.name
        _wait_for_path(received, timeout=10)
        assert received.read_bytes() == payload

        history_file = fake_home / ".glitter" / "history.jsonl"
        _wait_for_path(history_file, timeout=10)
        receive_entries: list[dict] = []
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                lines = [
                    json.loads(line)
                    for line in history_file.read_text(encoding="utf-8").splitlines()
                    if line.strip()
                ]
            except json.JSONDecodeError:
                time.sleep(0.05)
                continue
            receive_entries = [
                entry
                for entry in lines
                if entry.get("direction") == "receive" and entry.get("filename") == src_file.name
            ]
            if receive_entries:
                break
            time.sleep(0.05)
        assert receive_entries, "expected a receive history entry"
        latest = receive_entries[-1]
        assert latest.get("status") == "completed"
        assert latest.get("sha256") == expected_hash
        assert latest.get("target_path") == str(received)
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
        stdout_data, stderr_data = proc.communicate(timeout=20)

    assert proc.returncode == 0
    assert "Warning: encryption disabled" in (stdout_data or "")
    assert "Listening for incoming transfers" in (stdout_data or "")
    assert not (stderr_data or "").strip()


def test_cli_settings_direct_mode_updates_config_and_trust(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    config_file = _write_config(fake_home)

    known_peers = fake_home / ".glitter" / "known_peers.json"
    known_payload = {
        "peers": {
            "peer-1": {
                "peer_id": "peer-1",
                "name": "Friend",
                "fingerprint_display": "AA:BB",
                "fingerprint_hex": "aabbccdd",
                "public_key": "00",
                "first_seen": "2024-01-01T00:00:00Z",
                "last_seen": "2024-01-02T00:00:00Z",
            }
        }
    }
    known_peers.write_text(json.dumps(known_payload), encoding="utf-8")

    env = _env_for(fake_home)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "glitter",
            "settings",
            "--language",
            "zh",
            "--device-name",
            "Receiver",
            "--clear-trust",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0

    config_data = json.loads(config_file.read_text(encoding="utf-8"))
    assert config_data["language"] == "zh"
    assert config_data["device_name"] == "Receiver"
    assert config_data.get("auto_accept_trusted") == "off"

    if known_peers.exists():
        peers_payload = json.loads(known_peers.read_text(encoding="utf-8"))
        assert peers_payload.get("peers") in ({}, None)
