"""Regression tests for the `glitter history` command."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _setup_home(tmp_path: Path) -> Path:
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    config_dir = fake_home / ".glitter"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "language": "en",
                "device_name": "Tester",
                "device_id": "history-device",
                "encryption_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    return fake_home


def _env(fake_home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    env["USERPROFILE"] = str(fake_home)
    return env


def _write_sample_history(history_file: Path) -> None:
    history_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2024-01-01T00:00:00Z",
                        "direction": "send",
                        "status": "completed",
                        "filename": "foo.bin",
                        "size": 1,
                        "sha256": "deadbeef",
                        "local_device": "Tester",
                        "remote_name": "Peer",
                        "remote_ip": "127.0.0.1",
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2024-01-02T00:00:00Z",
                        "direction": "receive",
                        "status": "completed",
                        "filename": "bar.bin",
                        "size": 2,
                        "sha256": "cafebabe",
                        "local_device": "Tester",
                        "remote_name": "Peer2",
                        "remote_ip": "127.0.0.1",
                        "target_path": "/tmp/bar.bin",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_cli_history_clear_removes_history(tmp_path: Path) -> None:
    fake_home = _setup_home(tmp_path)
    history_file = fake_home / ".glitter" / "history.jsonl"
    history_file.write_text(
        json.dumps(
            {
                "timestamp": "2024-01-01T00:00:00Z",
                "direction": "send",
                "status": "completed",
                "filename": "foo.bin",
                "size": 1,
                "sha256": "deadbeef",
                "local_device": "Tester",
                "remote_name": "Peer",
                "remote_ip": "127.0.0.1",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    env = _env(fake_home)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "glitter",
            "history",
            "--clear",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert "Transfer history cleared" in (proc.stdout or "")
    assert not history_file.exists()


def test_cli_history_prints_existing_entries(tmp_path: Path) -> None:
    fake_home = _setup_home(tmp_path)
    history_file = fake_home / ".glitter" / "history.jsonl"
    _write_sample_history(history_file)

    env = _env(fake_home)
    proc = subprocess.run(
        [sys.executable, "-m", "glitter", "history"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    output = proc.stdout or ""
    assert "foo.bin" in output
    assert "bar.bin" in output


def test_cli_history_export_creates_file_in_cwd(tmp_path: Path) -> None:
    fake_home = _setup_home(tmp_path)
    history_file = fake_home / ".glitter" / "history.jsonl"
    _write_sample_history(history_file)

    env = _env(fake_home)
    run_dir = tmp_path / "run-default"
    run_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [sys.executable, "-m", "glitter", "history", "--export"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=30,
        cwd=run_dir,
    )
    assert proc.returncode == 0
    export_file = run_dir / "glitter-history-2.txt"
    assert export_file.exists()
    contents = export_file.read_text(encoding="utf-8")
    assert "foo.bin" in contents
    assert "bar.bin" in contents
    assert "History exported to" in (proc.stdout or "")


def test_cli_history_export_to_custom_directory(tmp_path: Path) -> None:
    fake_home = _setup_home(tmp_path)
    history_file = fake_home / ".glitter" / "history.jsonl"
    _write_sample_history(history_file)

    env = _env(fake_home)
    export_dir = tmp_path / "exports"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "glitter",
            "history",
            "--export",
            str(export_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    export_file = export_dir / "glitter-history-2.txt"
    assert export_file.exists()
    contents = export_file.read_text(encoding="utf-8")
    assert "foo.bin" in contents
    assert "bar.bin" in contents
    stdout = proc.stdout or ""
    assert str(export_file) in stdout


def test_cli_history_export_respects_quiet_flag(tmp_path: Path) -> None:
    fake_home = _setup_home(tmp_path)
    history_file = fake_home / ".glitter" / "history.jsonl"
    _write_sample_history(history_file)

    env = _env(fake_home)
    export_dir = tmp_path / "quiet-export"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "glitter",
            "history",
            "--export",
            str(export_dir),
            "-q",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    export_file = export_dir / "glitter-history-2.txt"
    assert export_file.exists()


def test_cli_history_export_fails_when_target_exists(tmp_path: Path) -> None:
    fake_home = _setup_home(tmp_path)
    history_file = fake_home / ".glitter" / "history.jsonl"
    _write_sample_history(history_file)

    env = _env(fake_home)
    export_dir = tmp_path / "exports-exist"
    export_file = export_dir / "glitter-history-2.txt"
    export_dir.mkdir(parents=True, exist_ok=True)
    export_file.write_text("placeholder", encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "glitter",
            "history",
            "--export",
            str(export_dir),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 1
    output = (proc.stdout or "") + (proc.stderr or "")
    assert "already exists" in output
    assert export_file.read_text(encoding="utf-8") == "placeholder"
