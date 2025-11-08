"""Unit tests for the TrustedPeerStore persistence logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import glitter.trust as trust_module


def _patch_storage(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "glitter-state"
    root.mkdir(parents=True, exist_ok=True)
    storage_file = root / "known_peers.json"
    monkeypatch.setattr(trust_module, "HISTORY_DIR", root, raising=False)
    monkeypatch.setattr(trust_module, "KNOWN_PEERS_FILE", storage_file, raising=False)
    return storage_file


def test_trusted_peer_store_remember_touch_and_reload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage_file = _patch_storage(monkeypatch, tmp_path)

    store = trust_module.TrustedPeerStore()
    entry = store.remember(
        peer_id="peer-123",
        name="Laptop",
        public_key=b"\x01" * 32,
        fingerprint_display="AA:BB",
        fingerprint_hex="aabbccddee",
    )

    assert entry.peer_id == "peer-123"
    assert store.get("peer-123") is not None
    first_seen = entry.first_seen

    store.touch("peer-123", name="Work Laptop")
    touched = store.get("peer-123")
    assert touched is not None
    assert touched.name == "Work Laptop"
    assert touched.first_seen == first_seen  # untouched
    assert touched.last_seen >= first_seen

    reloaded = trust_module.TrustedPeerStore()
    monkeypatch.setattr(trust_module, "HISTORY_DIR", storage_file.parent, raising=False)
    monkeypatch.setattr(trust_module, "KNOWN_PEERS_FILE", storage_file, raising=False)
    cached = reloaded.get("peer-123")
    assert cached is not None
    assert cached.fingerprint_hex == "aabbccddee"
    assert cached.name == "Work Laptop"


def test_trusted_peer_store_clear(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage_file = _patch_storage(monkeypatch, tmp_path)

    payload = {
        "peers": {
            "peer-1": {
                "peer_id": "peer-1",
                "name": "Device",
                "fingerprint_display": "AA",
                "fingerprint_hex": "aabb",
                "public_key": "00",
                "first_seen": "2024-01-01T00:00:00",
                "last_seen": "2024-01-01T00:00:01",
            }
        }
    }
    storage_file.write_text(json.dumps(payload), encoding="utf-8")

    store = trust_module.TrustedPeerStore()
    assert store.get("peer-1") is not None

    cleared = store.clear()
    assert cleared is True
    assert not storage_file.exists()
    assert store.get("peer-1") is None
