from __future__ import annotations

from pathlib import Path

import pytest
from rich.text import Text

from glitter.cli import display_menu, list_peers_cli, run_send_command
from glitter.discovery import PeerInfo
from glitter.history import HistoryRecord
from glitter.transfer import TransferTicket


class CaptureUI:
    def __init__(self):
        self.prints: list[str] = []
        self.last_prompt: str | None = None

    def print(self, message, *, end: str = "\n") -> None:
        self.prints.append(str(message))

    def blank(self):
        self.prints.append("<blank>")

    def input(self, prompt):
        self.last_prompt = str(prompt)
        return ""

    def flush(self):
        pass


class SimpleApp:
    def __init__(self):
        self.pending = []
        self.transfer_port = 8000
        self.identity_fingerprint_value = ""

    def list_peers(self):
        peer = PeerInfo(
            peer_id="1",
            name="test",
            ip="127.0.0.1",
            transfer_port=8000,
            language="en",
            version="0.0.2",
            last_seen=0.0,
        )
        return [peer]

    def identity_fingerprint(self):
        return self.identity_fingerprint_value

    def should_show_local_fingerprint(self, peer):
        return True

    def send_file(self, *args, **kwargs):
        return "accepted", "hash", "peer-id"

    def transfer_port(self):
        return 8000

    def stop(self):
        pass


def test_display_menu_prints_header(monkeypatch):
    ui = CaptureUI()
    display_menu(ui, "en", has_pending=2)
    assert any("prompt_choice" in line or "<blank>" in line for line in ui.prints)


def test_list_peers_cli_prints_peer(monkeypatch):
    ui = CaptureUI()
    app = SimpleApp()
    list_peers_cli(ui, app, "en")
    assert any("test" in line for line in ui.prints)


def test_run_send_command_handles_port_failure(monkeypatch, tmp_path):
    ui = CaptureUI()
    class FakeApp:
        def __init__(self):
            self.started = False

        def start(self):
            raise OSError("boom")

        def stop(self):
            self.started = False

    fake_app = FakeApp()

    def fake_initialize(debug):
        config = type("Conf", (), {"transfer_port": 1234})
        return fake_app, config, ui, "en"

    recorded: list[str] = []
    monkeypatch.setattr("glitter.cli.initialize_application", fake_initialize)
    monkeypatch.setattr("glitter.cli.emit_print", lambda _ui, message, quiet, error=False: recorded.append(str(message)))
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    code = run_send_command("127.0.0.1", str(tmp_path / "file.bin"))
    assert code == 1
    assert recorded
