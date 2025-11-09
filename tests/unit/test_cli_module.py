from __future__ import annotations

from pathlib import Path
from typing import Iterable

import threading
import types

import pytest
from rich.text import Text

from glitter import __version__
from glitter.cli import (
    ProgressTracker,
    _render_history_entry,
    emit_blank,
    emit_message,
    emit_print,
    export_history_records,
    handle_requests_cli,
    list_peers_cli,
    send_file_cli,
    show_updates,
    wait_for_completion,
)
from glitter import __version__
from glitter.discovery import PeerInfo
from glitter.history import HistoryRecord
from glitter.transfer import TransferTicket


class StubUI:
    def __init__(self, inputs: Iterable[str] | None = None):
        self._inputs = iter(inputs or [])
        self.lines: list[str] = []

    def print(self, message, *, end: str = "\n") -> None:
        self.lines.append(str(message))

    def blank(self) -> None:
        self.lines.append("<blank>")

    def carriage(self, message, padding: str = "") -> None:
        self.lines.append(f"{message}{padding}")

    def flush(self) -> None:
        pass

    def input(self, prompt) -> str:
        self.lines.append(str(prompt))
        try:
            return next(self._inputs)
        except StopIteration:
            return ""


class DummyApp:
    def __init__(self, *, transfer_port: int = 45846):
        self.transfer_port = transfer_port
        self.identity_fingerprint_value = "abc"
        self._pending: list[TransferTicket] = []
        self.log_entries: list[tuple[str, str]] = []
        self.should_show_fingerprint = True
        self._remembered: list[tuple[str, str]] = []
        self.debug = False
        self.default_download_dir = Path("/tmp")

    def list_peers(self) -> list[PeerInfo]:
        return []

    def identity_fingerprint(self) -> str:
        return self.identity_fingerprint_value

    def should_show_local_fingerprint(self, peer: PeerInfo) -> bool:
        return self.should_show_fingerprint

    def send_file(self, *args, **kwargs):
        self.log_entries.append(("send_file", args[0].peer_id))
        return "accepted", "hash", "peer-id"

    def remember_peer_id_for_ip(self, ip: str, peer_id: str) -> None:
        self._remembered.append((ip, peer_id))

    def cached_peer_id_for_ip(self, ip: str) -> str | None:
        return None

    def log_history(self, direction: str, status: str, **kwargs) -> None:
        self.log_entries.append((direction, status))

    def pending_requests(self) -> list[TransferTicket]:
        return list(self._pending)

    def reset_incoming_count(self) -> None:
        pass

    def accept_request(self, request_id: str, destination: Path) -> TransferTicket | None:
        for ticket in self._pending:
            if ticket.request_id == request_id:
                ticket.status = "completed"
                ticket.saved_path = destination / ticket.filename
                return ticket
        return None

    def decline_request(self, request_id: str) -> bool:
        return bool([t for t in self._pending if t.request_id == request_id])


class ImmediateThread:
    def __init__(self, target, name=None, daemon=None):
        self._target = target

    def start(self):
        self._target()

    def is_alive(self):
        return False

    def join(self, timeout=None):
        pass


class DummyProgressTracker:
    def __init__(self, ui, language, *, min_interval=0.1, enabled=True):
        self.last_bytes = 0
        self.last_total = 0
        self.min_interval = min_interval

    def update(self, transferred, total, *, force=False):
        self.last_bytes = transferred
        self.last_total = total
        return True

    def finish(self):
        pass


def test_wait_for_completion_timeout(monkeypatch):
    ticket = TransferTicket(
        request_id="req",
        filename="file.bin",
        filesize=1024,
        sender_name="peer",
        sender_ip="1.1.1.1",
        sender_language="en",
    )
    ticket.status = "pending"
    ui = StubUI()
    seq = iter([0.0, 0.0, 5.0])
    monkeypatch.setattr("glitter.cli.time.time", lambda: next(seq))
    monkeypatch.setattr("glitter.cli.time.sleep", lambda _: None)
    wait_for_completion(ui, ticket, "en", timeout=0.1)
    assert ticket.status == "failed"
    assert ticket.error == "timeout"


def test_show_updates_remote_failure(monkeypatch):
    ui = StubUI()
    monkeypatch.setattr("glitter.cli._fetch_remote_version", lambda *args, **kwargs: (None, "err"))
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    show_updates(ui, "en")
    assert any("update_check_failed" in line for line in ui.lines)


def test_export_history_records_no_records(monkeypatch):
    ui = StubUI()
    monkeypatch.setattr("glitter.cli.load_records", lambda limit=None: [])
    monkeypatch.setattr("glitter.cli.emit_message", lambda *args, **kwargs: ui.lines.append("history_empty"))
    result = export_history_records(ui, "en", None, quiet=False)
    assert result == 0
    assert "history_empty" in ui.lines[-1]


def test_export_history_records_write_error(monkeypatch, tmp_path):
    ui = StubUI()
    record = HistoryRecord(
        timestamp="now",
        direction="send",
        status="completed",
        filename="f",
        size=1,
        sha256=None,
        local_device="local",
        remote_name="peer",
        remote_ip="1.1.1.1",
        source_path=None,
        target_path=None,
        local_version=__version__,
        remote_version="1.0",
    )
    monkeypatch.setattr("glitter.cli.load_records", lambda limit=None: [record])
    emitted: list[str] = []
    monkeypatch.setattr("glitter.cli.emit_message", lambda *_args, **kwargs: emitted.append("fail"))
    monkeypatch.setattr(
        Path,
        "write_text",
        lambda self, content, encoding="utf-8": (_ for _ in ()).throw(OSError("boom")),
    )
    result = export_history_records(ui, "en", str(tmp_path / "out"), quiet=False)
    assert result == 1
    assert emitted


def test_render_history_entry_formats_text():
    record = HistoryRecord(
        timestamp="now",
        direction="receive",
        status="completed",
        filename="file.txt",
        size=10,
        sha256=None,
        local_device="local",
        remote_name="peer",
        remote_ip="10.0.0.1",
        source_path=None,
        target_path="/tmp/file.txt",
        local_version=__version__,
        remote_version="1.0",
    )
    entry = _render_history_entry(record, "en")
    assert isinstance(entry, Text)


@pytest.mark.usefixtures("monkeypatch")
def test_list_peers_cli_without_peers(monkeypatch):
    ui = StubUI()
    app = DummyApp()
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text("msg"))
    list_peers_cli(ui, app, "en")
    assert any("no peers" in line.lower() or "msg" in line for line in ui.lines)


def test_emit_helpers_quiet(monkeypatch):
    ui = StubUI()
    monkeypatch.setattr(
        "glitter.cli.show_message", lambda ui_, key, lang, **kwargs: ui_.print(f"{key}"))
    emit_message(ui, "en", "goodbye", True)
    emit_message(ui, "en", "goodbye", True, error=True)
    emit_print(ui, Text("hi"), True)
    emit_print(ui, Text("hi"), True, error=True)
    cnt = len(ui.lines)
    emit_blank(ui, True)
    assert len(ui.lines) == cnt


def test_send_file_cli_success(monkeypatch, tmp_path):
    ui = StubUI()
    peer = PeerInfo(
        peer_id="1",
        name="tester",
        ip="127.0.0.1",
        transfer_port=45846,
        language="en",
        version="0.0.1",
        last_seen=0.0,
    )
    app = DummyApp()
    app.list_peers = lambda: [peer]

    local_file = tmp_path / "file.txt"
    local_file.write_text("hello", encoding="utf-8")
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.ProgressTracker", DummyProgressTracker)
    monkeypatch.setattr("glitter.cli.threading.Thread", ImmediateThread)
    send_file_cli(
        ui,
        app,
        "en",
        preselected_peer=peer,
        preselected_path=local_file,
    )
    assert ("send", "completed") in app.log_entries


def test_send_file_cli_manual_selection(monkeypatch, tmp_path):
    ui = StubUI()
    peer = PeerInfo(
        peer_id="1",
        name="tester",
        ip="127.0.0.1",
        transfer_port=45846,
        language="en",
        version="0.0.1",
        last_seen=0.0,
    )
    app = DummyApp()
    app.list_peers = lambda: [peer]
    manual_info = {"normalized_ip": "1.2.3.4", "ip": "1.2.3.4", "port": 1234, "display": "manual"}
    local_file = tmp_path / "file.txt"
    local_file.write_text("hello", encoding="utf-8")
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.ProgressTracker", DummyProgressTracker)
    monkeypatch.setattr("glitter.cli.threading.Thread", ImmediateThread)
    send_file_cli(
        ui,
        app,
        "en",
        preselected_peer=peer,
        preselected_path=local_file,
        manual_target_info=manual_info,
    )
    assert ("send", "completed") in app.log_entries
    assert app._remembered[-1] == (manual_info["normalized_ip"], "peer-id")


def test_send_file_cli_manual_prompt(monkeypatch, tmp_path):
    ui = StubUI(inputs=["1.2.3.4:1234", str(tmp_path / "file.txt")])
    file_path = tmp_path / "file.txt"
    file_path.write_text("payload", encoding="utf-8")
    app = DummyApp()
    app.list_peers = lambda: []
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.ProgressTracker", DummyProgressTracker)
    monkeypatch.setattr("glitter.cli.threading.Thread", ImmediateThread)
    send_file_cli(ui, app, "en")
    assert ("send", "completed") in app.log_entries
    assert app._remembered[-1][0] == "1.2.3.4"


def test_send_file_cli_quiet_file_missing(monkeypatch, tmp_path):
    ui = StubUI()
    peer = PeerInfo(
        peer_id="1",
        name="tester",
        ip="127.0.0.1",
        transfer_port=45846,
        language="en",
        version=__import__("glitter").__version__,
        last_seen=0.0,
    )
    app = DummyApp()
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.show_message", lambda ui_, key, lang, **kwargs: ui_.print(key))
    send_file_cli(
        ui,
        app,
        "en",
        preselected_peer=peer,
        preselected_path=tmp_path / "missing.txt",
        quiet=True,
    )
    assert any("file_not_found" in line for line in ui.lines)


def test_handle_requests_cli_accept(monkeypatch, tmp_path):
    ui = StubUI(inputs=["1", "a", str(tmp_path)])
    ticket = TransferTicket(
        request_id="req-1",
        filename="file.txt",
        filesize=1,
        sender_name="peer",
        sender_ip="10.0.0.1",
        sender_language="en",
    )
    ticket.identity_status = "trusted"
    app = DummyApp()
    app._pending.append(ticket)
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.wait_for_completion", lambda *args, **kwargs: None)
    handle_requests_cli(ui, app, "en")
    assert any("receive_done" in line for line in ui.lines)


def test_handle_requests_cli_decline(monkeypatch):
    ui = StubUI(inputs=["1", "d"])
    ticket = TransferTicket(
        request_id="req-1",
        filename="file.txt",
        filesize=1,
        sender_name="peer",
        sender_ip="10.0.0.1",
        sender_language="en",
    )
    ticket.identity_status = "trusted"
    app = DummyApp()
    app._pending.append(ticket)
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    handle_requests_cli(ui, app, "en")
    assert ("receive", "declined") in app.log_entries


def test_handle_requests_cli_invalid_inputs(monkeypatch):
    ui = StubUI(inputs=["0", "1", "x", "d"])
    ticket = TransferTicket(
        request_id="req-1",
        filename="file.txt",
        filesize=1,
        sender_name="peer",
        sender_ip="10.0.0.1",
        sender_language="en",
    )
    ticket.identity_status = "trusted"
    app = DummyApp()
    app._pending.append(ticket)
    messages: list[str] = []
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.show_message", lambda ui, key, lang, **kwargs: messages.append(key))
    handle_requests_cli(ui, app, "en")
    assert ("receive", "declined") in app.log_entries
    assert "invalid_choice" in messages
