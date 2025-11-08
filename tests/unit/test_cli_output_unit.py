"""Unit tests for glitter.cli output helpers and history display."""

from __future__ import annotations

import pytest

import glitter.cli as cli
from glitter.history import HistoryRecord


class DummyUI:
    def __init__(self) -> None:
        self.printed: list[str] = []
        self.blanks = 0

    def print(self, message, *, end: str = "\n") -> None:  # noqa: D401 - capture
        self.printed.append(str(message))

    def blank(self) -> None:
        self.blanks += 1


def test_normalize_auto_accept_mode_variants() -> None:
    assert cli.normalize_auto_accept_mode("Yes") == "trusted"
    assert cli.normalize_auto_accept_mode("   全部  ") == "all"
    assert cli.normalize_auto_accept_mode("OFF") == "off"
    assert cli.normalize_auto_accept_mode(None) is None


def test_normalize_auto_accept_mode_invalid() -> None:
    assert cli.normalize_auto_accept_mode("maybe") is None
    assert cli.normalize_auto_accept_mode("") is None


def test_emit_helpers_respect_quiet(monkeypatch: pytest.MonkeyPatch):
    recorded: list[str] = []

    def fake_show_message(ui, key, language, **kwargs):  # noqa: ARG001
        recorded.append(f"msg:{key}")

    monkeypatch.setattr(cli, "show_message", fake_show_message)
    ui = DummyUI()
    cli.emit_message(ui, "en", "foo", quiet=True)
    assert recorded == []
    cli.emit_message(ui, "en", "foo", quiet=True, error=True)
    assert recorded == ["msg:foo"]

    cli.emit_print(ui, "hello", quiet=True)
    assert ui.printed == []
    cli.emit_print(ui, "error", quiet=True, error=True)
    assert ui.printed == ["error"]

    cli.emit_blank(ui, quiet=True)
    assert ui.blanks == 0
    cli.emit_blank(ui, quiet=False)
    assert ui.blanks == 1


@pytest.fixture()
def fake_render(monkeypatch: pytest.MonkeyPatch):
    def _fake_render(key: str, language: str, **kwargs):  # noqa: ARG001
        text = f"{key}:{kwargs.get('filename','')}"

        class _FakeText:
            def __init__(self, value: str) -> None:
                self.plain = value

            def __str__(self) -> str:
                return self.plain

        return _FakeText(text)

    monkeypatch.setattr(cli, "render_message", _fake_render)


def test_show_history_when_empty(monkeypatch: pytest.MonkeyPatch, fake_render) -> None:  # noqa: ARG001
    monkeypatch.setattr(cli, "load_records", lambda limit: [])
    seen: list[str] = []

    def fake_show_message(ui, key, language, **kwargs):  # noqa: ARG001
        seen.append(key)

    monkeypatch.setattr(cli, "show_message", fake_show_message)
    ui = DummyUI()
    cli.show_history(ui, "en")
    assert seen == ["history_empty"]
    assert ui.printed == []


def test_show_history_formats_records(monkeypatch: pytest.MonkeyPatch, fake_render) -> None:  # noqa: ARG001
    records = [
        HistoryRecord(
            timestamp="2024-01-01T00:00:00+00:00",
            direction="send",
            status="completed",
            filename="foo.bin",
            size=1024,
            sha256=None,
            local_device="local",
            remote_name="peer",
            remote_ip="127.0.0.1",
        ),
        HistoryRecord(
            timestamp="2024-01-02T00:00:00+00:00",
            direction="receive",
            status="completed",
            filename="bar.bin",
            size=2048,
            sha256=None,
            local_device="local",
            remote_name="peer2",
            remote_ip="127.0.0.1",
            target_path="/tmp/bar.bin",
        ),
        HistoryRecord(
            timestamp="2024-01-03T00:00:00+00:00",
            direction="send",
            status="failed",
            filename="bad.bin",
            size=0,
            sha256=None,
            local_device="local",
            remote_name="peer3",
            remote_ip="127.0.0.1",
        ),
    ]
    monkeypatch.setattr(cli, "load_records", lambda limit: records)

    show_calls: list[str] = []

    def fake_show_message(ui, key, language, **kwargs):  # noqa: ARG001
        show_calls.append(key)

    monkeypatch.setattr(cli, "show_message", fake_show_message)

    ui = DummyUI()
    cli.show_history(ui, "en")
    # should show header then print 3 entries (in reverse order)
    assert show_calls[0] == "history_header"
    assert ui.printed == [
        "history_entry_failed:bad.bin",
        "history_entry_receive:bar.bin",
        "history_entry_send:foo.bin",
    ]
