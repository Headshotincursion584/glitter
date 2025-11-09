from __future__ import annotations

import io
from pathlib import Path

import pytest
from rich.text import Text

from glitter import __version__
from glitter.cli import (
    export_history_records,
    show_history,
    show_updates,
    wait_for_completion,
)
from glitter.history import HistoryRecord
from glitter.transfer import TransferTicket
from glitter.ui import TerminalUI


class CounterUI(TerminalUI):
    def __init__(self):
        super().__init__()
        self.prints: list[str] = []

    def print(self, message=Text(""), *, end: str = "\n"):
        self.prints.append(str(message))

    def blank(self):
        super().blank()


def _make_record(direction: str = "send") -> HistoryRecord:
    return HistoryRecord(
        timestamp="now",
        direction=direction,
        status="completed",
        filename="file.bin",
        size=1,
        sha256=None,
        local_device="tester",
        remote_name="peer",
        remote_ip="1.1.1.1",
        source_path=None,
        target_path=None,
        local_version=__version__,
        remote_version="1.0",
    )


def test_show_history_with_entries(monkeypatch):
    ui = CounterUI()
    records = [_make_record("receive")]
    monkeypatch.setattr("glitter.cli.load_records", lambda limit: records)
    monkeypatch.setattr("glitter.cli.show_message", lambda ui_, key, lang, **kwargs: ui_.prints.append(key))
    show_history(ui, "en", limit=1)
    assert any("history_header" in line for line in ui.prints)


def test_export_history_records_success(monkeypatch, tmp_path):
    ui = CounterUI()
    record = _make_record()
    monkeypatch.setattr("glitter.cli.load_records", lambda limit=None: [record])
    monkeypatch.setattr("glitter.cli.emit_message", lambda *args, **kwargs: ui.prints.append("ok"))
    output = tmp_path / "export"
    output.mkdir()
    result = export_history_records(ui, "en", str(output), quiet=False)
    assert result == 0
    assert (output / "glitter-history-1.txt").exists()


def test_show_updates_success(monkeypatch):
    ui = CounterUI()
    monkeypatch.setattr("glitter.cli._fetch_remote_version", lambda *args, **kwargs: ("1.2.3", None))
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.show_message", lambda ui_, key, lang, **kwargs: ui_.prints.append(key))
    show_updates(ui, "en")
    assert any("latest_version" in line for line in ui.prints)


def test_wait_for_completion_partial(monkeypatch):
    ui = CounterUI()
    ticket = TransferTicket(
        request_id="req",
        filename="test",
        filesize=2,
        sender_name="peer",
        sender_ip="1.1.1.1",
        sender_language="en",
    )
    ticket.status = "receiving"
    ticket.bytes_transferred = 1
    seq = iter([0.0, 0.0, 0.5, 0.5, 5.0])
    monkeypatch.setattr("glitter.cli.time.time", lambda: next(seq))
    monkeypatch.setattr("glitter.cli.time.sleep", lambda _: None)
    wait_for_completion(ui, ticket, "en", timeout=0.1)
    assert ticket.status in {"completed", "failed"}
