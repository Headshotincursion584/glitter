"""Unit tests for glitter.app.GlitterApp behaviors."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pytest

from glitter.app import GlitterApp
from glitter.discovery import PeerInfo
from glitter.transfer import TransferTicket


class DummyUI:
    def __init__(self) -> None:
        self.printed: list[str] = []
        self.blank_calls = 0
        self.flush_calls = 0

    def print(self, message, *, end: str = "\n") -> None:  # noqa: D401 - simple capture
        self.printed.append(str(message))

    def blank(self) -> None:  # noqa: D401 - simple counter
        self.blank_calls += 1

    def flush(self) -> None:  # noqa: D401 - simple counter
        self.flush_calls += 1


class DummyTransferService:
    def __init__(self) -> None:
        self.port = 45846
        self.allow_ephemeral_fallback = True
        self.accept_calls: List[tuple[str, Path]] = []
        self.decline_calls: List[str] = []
        self.accept_result: Optional[TransferTicket] = None
        self.active_receiving = False

    # --- API surface patched into GlitterApp during tests ---
    def set_encryption_enabled(self, enabled: bool) -> None:  # noqa: D401
        self.encryption_enabled = enabled

    def get_identity_fingerprint(self) -> str:  # noqa: D401 - deterministic fingerprint
        return "fingerprint"

    def update_identity(self, *args, **kwargs) -> None:  # noqa: D401 - no-op
        return None

    def start(self) -> None:  # noqa: D401 - no-op
        return None

    def stop(self) -> None:  # noqa: D401 - no-op
        return None

    def pending_requests(self) -> list[TransferTicket]:  # noqa: D401
        return []

    def decline_request(self, request_id: str) -> bool:  # noqa: D401
        self.decline_calls.append(request_id)
        return True

    def accept_request(self, request_id: str, directory: Path) -> Optional[TransferTicket]:  # noqa: D401
        self.accept_calls.append((request_id, directory))
        return self.accept_result

    def has_active_receiving(self) -> bool:  # noqa: D401
        return self.active_receiving


class ImmediateThread:
    def __init__(self, target, name=None, daemon=None) -> None:  # noqa: D401
        self._target = target

    def start(self) -> None:  # noqa: D401 - run synchronously
        self._target()


def make_ticket(identity_status: str = "trusted") -> TransferTicket:
    return TransferTicket(
        request_id="req-1",
        filename="file.txt",
        filesize=1024,
        sender_name="Peer",
        sender_ip="10.0.0.10",
        sender_language="en",
        identity_status=identity_status,
        sender_version="1.0",
    )


@pytest.fixture()
def app_setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    ui = DummyUI()
    service = DummyTransferService()

    def fake_create(self, bind_port: int, allow_fallback: bool):
        service.port = bind_port or service.port
        service.allow_ephemeral_fallback = allow_fallback
        return service

    monkeypatch.setattr(GlitterApp, "_create_transfer_service", fake_create)
    download_dir = tmp_path / "downloads"
    download_dir.mkdir(parents=True)
    app = GlitterApp(
        device_id="device123",
        device_name="Tester",
        language="en",
        default_download_dir=download_dir,
        transfer_port=45846,
        ui=ui,
    )
    return app, service, ui, download_dir


def _make_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service=None):
    ui = DummyUI()
    service = service or DummyTransferService()

    def fake_create(self, bind_port: int, allow_fallback: bool):
        service.port = bind_port or service.port
        service.allow_ephemeral_fallback = allow_fallback
        return service

    monkeypatch.setattr(GlitterApp, "_create_transfer_service", fake_create)
    download_dir = tmp_path / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    app = GlitterApp(
        device_id="device123",
        device_name="Tester",
        language="en",
        default_download_dir=download_dir,
        transfer_port=45846,
        ui=ui,
    )
    return app, service, ui, download_dir


class StubTrustStore:
    def __init__(self) -> None:
        self.cleared = False

    def get(self, peer_id: str):
        return self if peer_id == "known" else None

    def clear(self) -> bool:
        self.cleared = True
        return True


def test_auto_accept_trusted_logs_history(monkeypatch: pytest.MonkeyPatch, app_setup):
    app, service, ui, download_dir = app_setup
    records = []
    monkeypatch.setattr("glitter.app.append_record", lambda record: records.append(record))
    monkeypatch.setattr("glitter.app.render_message", lambda key, lang, **kw: f"{key}:{kw.get('filename','')}" )
    monkeypatch.setattr("glitter.app.threading.Thread", ImmediateThread)

    accepted_ticket = make_ticket(identity_status="trusted")
    accepted_ticket.status = "completed"
    accepted_ticket.saved_path = download_dir / "file.txt"
    accepted_ticket.expected_hash = "hash123"
    service.accept_result = accepted_ticket

    app.set_auto_accept_mode("trusted")
    app._handle_incoming_request(make_ticket(identity_status="trusted"))

    assert service.accept_calls == [("req-1", download_dir)]
    assert any("auto_accept_trusted_notice" in msg for msg in ui.printed)
    assert records and records[-1].status == "completed"
    assert records[-1].target_path == str(accepted_ticket.saved_path)


def test_auto_rejects_untrusted_when_configured(monkeypatch: pytest.MonkeyPatch, app_setup):
    app, service, ui, _ = app_setup
    records = []
    monkeypatch.setattr("glitter.app.append_record", lambda record: records.append(record))
    monkeypatch.setattr("glitter.app.render_message", lambda key, lang, **kw: key)

    app.set_auto_accept_mode("trusted")
    app.set_auto_reject_untrusted(True)
    app._handle_incoming_request(make_ticket(identity_status="unknown"))

    assert service.decline_calls == ["req-1"]
    assert "auto_accept_trusted_rejected" in ui.printed
    assert records == []


def test_download_dir_and_modes(monkeypatch: pytest.MonkeyPatch, app_setup, tmp_path):
    app, _, _, download_dir = app_setup
    new_dir = download_dir / "new"
    result = app.set_default_download_dir(new_dir)
    assert result == new_dir
    assert app.default_download_dir == new_dir

    fallback = tmp_path / "fallback"
    monkeypatch.setattr("glitter.app.ensure_download_dir", lambda: fallback)
    reset_value = app.reset_default_download_dir()
    assert reset_value == fallback
    assert app.default_download_dir == fallback

    app.set_auto_accept_mode(True)
    assert app.auto_accept_mode == "trusted"
    app.set_auto_accept_mode("ALL ")
    assert app.auto_accept_mode == "all"
    app.set_auto_accept_mode("unknown")
    assert app.auto_accept_mode == "off"
    app.set_auto_accept_trusted(False)
    assert app.auto_accept_mode == "off"
    app.set_auto_reject_untrusted(True)
    assert app._auto_reject_untrusted
    assert app.auto_accept_trusted is False


def test_peer_cache_and_trust_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    app, _, _, _ = _make_app(monkeypatch, tmp_path)
    trust_store = StubTrustStore()
    app._trust_store = trust_store
    peer = PeerInfo("known", "Peer", "127.0.0.1", 45846, "en", "1.0", 0.0)
    assert app.should_show_local_fingerprint(peer) is False
    peer.peer_id = ""
    assert app.should_show_local_fingerprint(peer) is True
    app._trust_store = None
    assert app.should_show_local_fingerprint(peer) is True

    app.remember_peer_id_for_ip("1.2.3.4", "cached")
    assert app.cached_peer_id_for_ip("1.2.3.4") == "cached"
    app.remember_peer_id_for_ip("1.2.3.4", "")
    assert app.cached_peer_id_for_ip("1.2.3.4") == "cached"

    app._trust_store = trust_store
    app._trust_store.clear()
    assert trust_store.cleared
    assert app.clear_trusted_fingerprints()
    app._trust_store = None
    assert app.clear_trusted_fingerprints() is False


def test_list_peers_without_discovery(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    app, _, _, _ = _make_app(monkeypatch, tmp_path)
    assert app.list_peers() == []


def test_change_transfer_port_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    services: list[DummyTransferService] = []

    class PortService(DummyTransferService):
        def __init__(self, bind_port, allow_fallback):
            super().__init__()
            self.port = bind_port or self.port
            self.allow_ephemeral_fallback = allow_fallback
            self.started = False

        def start(self):
            self.started = True

        def stop(self):
            self.started = False

    def fake_create(self, bind_port: int, allow_fallback: bool):
        service = PortService(bind_port, allow_fallback)
        services.append(service)
        return service

    monkeypatch.setattr(GlitterApp, "_create_transfer_service", fake_create)
    app = GlitterApp(
        device_id="device",
        device_name="Tester",
        language="en",
        default_download_dir=tmp_path,
        transfer_port=45846,
        ui=DummyUI(),
    )

    new_port = 12345
    port = app.change_transfer_port(new_port)
    assert port == new_port
    assert services[-1].started


def test_change_transfer_port_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    services: list[DummyTransferService] = []

    class FailingService(DummyTransferService):
        def start(self):
            raise OSError("boom")

    def fake_create(self, bind_port: int, allow_fallback: bool):
        if not services:
            service = DummyTransferService()
        else:
            service = FailingService()
        services.append(service)
        return service

    monkeypatch.setattr(GlitterApp, "_create_transfer_service", fake_create)
    app = GlitterApp(
        device_id="device",
        device_name="Tester",
        language="en",
        default_download_dir=tmp_path,
        transfer_port=45846,
        ui=DummyUI(),
    )

    old_service = services[0]
    with pytest.raises(OSError):
        app.change_transfer_port(20000)
    assert app._transfer_service is old_service


def test_cancel_pending_requests_logs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    service = DummyTransferService()
    ticket = make_ticket()
    ticket.expected_hash = "hash"
    ticket.content_type = "file"

    class PendingService(DummyTransferService):
        def pending_requests(self):
            return [ticket]

        def decline_request(self, request_id: str) -> bool:
            return True

    app, _, ui, download_dir = _make_app(monkeypatch, tmp_path, PendingService())
    records: list = []
    monkeypatch.setattr("glitter.app.append_record", lambda record: records.append(record))
    app.cancel_pending_requests(status="failed")

    assert records
    assert records[-1].status == "failed"


def test_handle_request_cancelled_logs(monkeypatch: pytest.MonkeyPatch, app_setup):
    app, _, ui, _ = app_setup
    records = []
    monkeypatch.setattr("glitter.app.append_record", lambda record: records.append(record))
    monkeypatch.setattr("glitter.app.render_message", lambda key, lang, **kw: key)
    ticket = make_ticket()
    app._handle_request_cancelled(ticket)
    assert records
    assert ui.printed
    assert "incoming_cancelled" in ui.printed[-1]
