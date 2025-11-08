"""Unit tests for `run_send_command` and `run_receive_command`."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import glitter.cli as cli
from glitter.discovery import PeerInfo
import glitter.ui as ui_module


class FakeText(str):
    @property
    def plain(self) -> str:
        return str(self)


class DummyUI:
    def __init__(self) -> None:
        self.printed: list[str] = []

    def print(self, message, *, end: str = "\n") -> None:  # noqa: D401 - capture
        self.printed.append(str(message))

    def blank(self) -> None:
        self.printed.append("<blank>")


class SendReceiveApp:
    def __init__(self, tmp_path: Path) -> None:
        self.device_name = "Tester"
        self.transfer_port = 45846
        self.default_download_dir = tmp_path / "downloads"
        self.default_download_dir.mkdir(parents=True, exist_ok=True)
        self._peers: list[PeerInfo] = []
        self.started = False
        self.stopped = False
        self.cancelled = False
        self.auto_mode = "off"
        self.auto_reject = None
        self._encryption_enabled = True
        self._cached: dict[str, str] = {}

    def list_peers(self) -> list[PeerInfo]:
        return list(self._peers)

    def set_peers(self, peers: list[PeerInfo]) -> None:
        self._peers = peers

    def cached_peer_id_for_ip(self, ip: str) -> str | None:
        return self._cached.get(ip)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def cancel_pending_requests(self) -> None:
        self.cancelled = True

    def set_default_download_dir(self, directory: Path) -> Path:
        self.default_download_dir = directory
        return directory

    def set_auto_accept_mode(self, mode: str) -> None:
        self.auto_mode = mode

    def set_auto_reject_untrusted(self, enabled: bool) -> None:
        self.auto_reject = enabled

    def change_transfer_port(self, new_port: int) -> int:
        if not (1 <= new_port <= 65535):
            raise ValueError("invalid port")
        self.transfer_port = new_port
        return new_port

    @property
    def encryption_enabled(self) -> bool:
        return self._encryption_enabled

    def set_encryption_enabled(self, enabled: bool) -> None:
        self._encryption_enabled = enabled


@pytest.fixture(autouse=True)
def fake_render(monkeypatch: pytest.MonkeyPatch):
    def _fake_render(key: str, language: str, **kwargs):  # noqa: ARG001
        suffix = kwargs.get("filename") or ""
        return FakeText(f"{key}:{suffix}")

    monkeypatch.setattr(cli, "render_message", _fake_render)
    monkeypatch.setattr(ui_module, "render_message", _fake_render)


@pytest.fixture()
def send_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    app = SendReceiveApp(tmp_path)
    config = SimpleNamespace(transfer_port=None)
    ui = DummyUI()

    def fake_init(debug: bool):  # noqa: ARG001
        return app, config, ui, "en"

    monkeypatch.setattr(cli, "initialize_application", fake_init)
    return app, config, ui


@pytest.fixture()
def receive_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    app = SendReceiveApp(tmp_path)
    config = SimpleNamespace(auto_accept_trusted="trusted", transfer_port=app.transfer_port)
    ui = DummyUI()

    def fake_init(debug: bool):  # noqa: ARG001
        return app, config, ui, "en"

    monkeypatch.setattr(cli, "initialize_application", fake_init)
    return app, config, ui


def test_run_send_command_manual_ip_invokes_send_cli(monkeypatch: pytest.MonkeyPatch, send_app, tmp_path: Path):
    app, _, _ = send_app
    payload = tmp_path / "sample.bin"
    payload.write_text("data", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_send_file(ui, app_obj, language, **kwargs):  # noqa: ARG001
        captured.update(kwargs)

    monkeypatch.setattr(cli, "send_file_cli", fake_send_file)

    exit_code = cli.run_send_command("127.0.0.1", str(payload))
    assert exit_code == 0
    assert app.started and app.stopped and app.cancelled
    preselected = captured.get("preselected_peer")
    assert preselected is not None
    assert preselected.ip == "127.0.0.1"
    assert isinstance(captured.get("manual_target_info"), dict)


def test_run_send_command_missing_file_errors(monkeypatch: pytest.MonkeyPatch, send_app):
    app, _, _ = send_app
    peers = [
        PeerInfo(
            peer_id="p1",
            name="Device",
            ip="192.168.1.10",
            transfer_port=app.transfer_port,
            language="en",
            version="1",
            last_seen=0.0,
        )
    ]
    app.set_peers(peers)
    messages: list[str] = []
    monkeypatch.setattr(cli, "emit_message", lambda ui, lang, key, quiet, **kwargs: messages.append(key))

    exit_code = cli.run_send_command("Device", str(Path("/tmp/does-not-exist")))
    assert exit_code == 1
    assert messages[-1] == "file_not_found"


def test_run_send_command_ambiguous_name(monkeypatch: pytest.MonkeyPatch, send_app):
    app, _, ui = send_app
    peers = [
        PeerInfo(
            peer_id="peer1",
            name="Alpha",
            ip="10.0.0.1",
            transfer_port=app.transfer_port,
            language="en",
            version="1",
            last_seen=0.0,
        ),
        PeerInfo(
            peer_id="peer2",
            name="Alpha",
            ip="10.0.0.2",
            transfer_port=app.transfer_port,
            language="en",
            version="1",
            last_seen=0.0,
        ),
    ]
    app.set_peers(peers)
    captured: list[str] = []
    monkeypatch.setattr(cli, "emit_print", lambda ui_obj, message, quiet, *, error=False: captured.append(str(message)))

    exit_code = cli.run_send_command("Alpha", str(Path(__file__)))
    assert exit_code == 1
    assert captured and "peer_name_ambiguous" in captured[0]
    assert ui.printed == []


def test_run_receive_command_invalid_mode(monkeypatch: pytest.MonkeyPatch, receive_app):
    _, _, _ = receive_app
    messages: list[str] = []
    monkeypatch.setattr(cli, "emit_message", lambda ui, lang, key, quiet, **kwargs: messages.append(key))

    exit_code = cli.run_receive_command("invalid", None, None)
    assert exit_code == 1
    assert messages == ["receive_mode_invalid"]


def test_run_receive_command_sets_dir_port_and_handles_loop(monkeypatch: pytest.MonkeyPatch, receive_app, tmp_path: Path):
    app, config, _ = receive_app
    target_dir = tmp_path / "incoming"
    addresses = ["127.0.0.1"]

    monkeypatch.setattr(cli, "local_network_addresses", lambda: addresses)
    monkeypatch.setattr(cli.time, "sleep", lambda _: (_ for _ in ()).throw(KeyboardInterrupt))
    monkeypatch.setattr(cli, "emit_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli, "emit_print", lambda *args, **kwargs: None)

    exit_code = cli.run_receive_command(None, str(target_dir), "5000", no_encryption=True)
    assert exit_code == 0
    assert app.transfer_port == 5000
    assert app.default_download_dir == target_dir.resolve()
    assert app.auto_mode == "trusted"
    assert app.auto_reject is True
    assert app.encryption_enabled is True  # restored after loop
    assert app.cancelled and app.stopped


def test_run_receive_command_invalid_port_value(monkeypatch: pytest.MonkeyPatch, receive_app):
    messages: list[str] = []
    monkeypatch.setattr(cli, "emit_message", lambda ui, lang, key, quiet, **kwargs: messages.append(key))

    exit_code = cli.run_receive_command(None, None, "not-a-port")
    assert exit_code == 1
    assert messages[-1] == "settings_port_invalid"
