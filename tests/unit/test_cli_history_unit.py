"""Unit tests covering history-related CLI helpers."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

import glitter.cli as cli
from glitter.history import HistoryRecord


class StubUI:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message, *, end: str = "\n") -> None:  # noqa: D401 - simple capture
        self.messages.append(str(message))

    def blank(self) -> None:
        self.messages.append("<blank>")


@pytest.fixture()
def history_init(monkeypatch: pytest.MonkeyPatch):
    ui = StubUI()
    app = SimpleNamespace()
    config = SimpleNamespace(transfer_port=None)

    def fake_init(debug: bool):  # noqa: ARG001
        return app, config, ui, "en"

    monkeypatch.setattr(cli, "initialize_application", fake_init)
    return ui


def test_run_history_command_requires_direct_quiet(monkeypatch: pytest.MonkeyPatch, history_init: StubUI):
    captured: list[tuple[str, bool, bool]] = []

    def fake_emit(ui, language, key, quiet, *, error=False, **kwargs):  # noqa: ARG001
        captured.append((key, quiet, error))

    monkeypatch.setattr(cli, "emit_message", fake_emit)

    exit_code = cli.run_history_command(quiet=True)
    assert exit_code == 2
    assert captured == [("cli_quiet_direct_error", True, True)]


def test_run_history_command_export_invokes_helper(monkeypatch: pytest.MonkeyPatch, history_init: StubUI):
    called: dict[str, object] = {}

    def fake_export(ui, language, export_path, quiet):  # noqa: ARG001
        called["path"] = export_path
        called["quiet"] = quiet
        called["language"] = language
        return 0

    monkeypatch.setattr(cli, "export_history_records", fake_export)
    monkeypatch.setattr(cli, "show_history", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("show_history not expected")))

    exit_code = cli.run_history_command(export="/tmp/export-dir")
    assert exit_code == 0
    assert called == {"path": "/tmp/export-dir", "quiet": False, "language": "en"}


def test_run_history_command_export_failure_returns_code(monkeypatch: pytest.MonkeyPatch, history_init: StubUI):
    monkeypatch.setattr(cli, "export_history_records", lambda *args, **kwargs: 5)
    monkeypatch.setattr(cli, "show_history", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("show_history not expected")))

    exit_code = cli.run_history_command(export="/tmp/fail")
    assert exit_code == 5


def test_run_history_command_clear_clears(monkeypatch: pytest.MonkeyPatch, history_init: StubUI):
    cleared = {"called": False}

    def fake_clear() -> None:
        cleared["called"] = True

    monkeypatch.setattr(cli, "clear_history", fake_clear)
    exit_code = cli.run_history_command(clear=True)
    assert exit_code == 0
    assert cleared["called"] is True


def test_run_history_command_shows_history(monkeypatch: pytest.MonkeyPatch, history_init: StubUI):
    observed: list[tuple] = []

    def fake_show(ui, language):
        observed.append((ui, language))

    monkeypatch.setattr(cli, "show_history", fake_show)
    exit_code = cli.run_history_command()
    assert exit_code == 0
    assert len(observed) == 1
    assert observed[0][1] == "en"


def test_export_history_records_writes_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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
        )
    ]
    monkeypatch.setattr(cli, "load_records", lambda limit: records)

    emitted: list[str] = []

    def fake_emit(ui, language, key, quiet, *, error=False, **kwargs):  # noqa: ARG001
        emitted.append(key)

    monkeypatch.setattr(cli, "emit_message", fake_emit)

    export_dir = tmp_path / "exports"
    exit_code = cli.export_history_records(object(), "en", str(export_dir), quiet=False)
    assert exit_code == 0
    output = (export_dir / "glitter-history-1.txt").read_text(encoding="utf-8")
    assert "Recent transfers" in output
    assert "foo.bin" in output
    assert emitted[-1] == "history_export_success"


def test_export_history_records_errors_when_file_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    records = [
        HistoryRecord(
            timestamp="2024-01-01T00:00:00+00:00",
            direction="send",
            status="completed",
            filename="foo.bin",
            size=1,
            sha256=None,
            local_device="local",
            remote_name="peer",
            remote_ip="127.0.0.1",
        )
    ]
    monkeypatch.setattr(cli, "load_records", lambda limit: records)

    emitted: list[str] = []

    def fake_emit(ui, language, key, quiet, *, error=False, **kwargs):  # noqa: ARG001
        emitted.append(key)

    monkeypatch.setattr(cli, "emit_message", fake_emit)

    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    target = export_dir / "glitter-history-1.txt"
    target.write_text("existing", encoding="utf-8")

    exit_code = cli.export_history_records(object(), "en", str(export_dir), quiet=False)
    assert exit_code == 1
    assert emitted[-1] == "history_export_exists"
