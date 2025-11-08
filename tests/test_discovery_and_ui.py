"""Unit tests for discovery/tracker helpers."""

from __future__ import annotations

import time

from glitter.discovery import DiscoveryService, PeerInfo
from glitter.ui import ProgressTracker


def test_discovery_get_peers_filters_stale():
    service = DiscoveryService(
        peer_id="self",
        device_name="Tester",
        language="en",
        transfer_port=45846,
        beacon_interval=10,
        peer_timeout=0.01,
    )
    now = time.time()
    service._peers = {  # type: ignore[attr-defined]
        "fresh": PeerInfo("fresh", "A", "127.0.0.1", 45846, "en", "1.0", now),
        "old": PeerInfo("old", "B", "127.0.0.2", 45846, "en", "1.0", now - 1),
    }
    peers = service.get_peers()
    assert len(peers) == 1
    assert peers[0].peer_id == "fresh"


def test_discovery_reply_cooldown():
    service = DiscoveryService("self", "Tester", "en", 45846)
    now = time.time()
    assert service._should_reply("peer", now) is True  # first time
    assert service._should_reply("peer", now + 1) is False  # within cooldown
    assert service._should_reply("peer", now + 10) is True


def test_progress_tracker_updates_and_finishes():
    class StubUI:
        def __init__(self) -> None:
            self.lines: list[str] = []

        def carriage(self, message, padding=""):
            self.lines.append(str(message))

        def blank(self):
            self.lines.append("<blank>")

    ui = StubUI()
    tracker = ProgressTracker(ui, "en", min_interval=0)
    tracker.update(512, 1024, force=True)
    tracker.update(1024, 1024, force=True)
    tracker.finish()
    assert any("512" in line for line in ui.lines)
    assert ui.lines[-1] == "<blank>"
