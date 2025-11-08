"""Tests for resilient config loading behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

import glitter.config as config_module


def test_load_config_handles_corrupt_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_history = tmp_path / ".glitter"
    fake_history.mkdir(parents=True, exist_ok=True)
    config_file = fake_history / "config.json"
    config_file.write_text("{not-json", encoding="utf-8")

    monkeypatch.setattr(config_module, "HISTORY_DIR", fake_history, raising=False)
    monkeypatch.setattr(config_module, "CONFIG_FILE", config_file, raising=False)

    cfg = config_module.load_config()
    assert cfg.language is None
    assert cfg.device_name is None
    assert cfg.transfer_port is None
    assert cfg.auto_accept_trusted == "off"
