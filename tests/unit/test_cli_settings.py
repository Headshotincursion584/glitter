from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Iterable

import pytest

from rich.text import Text

from glitter.cli import (
    LocalizedArgumentParser,
    prompt_device_name,
    prompt_language_choice,
    settings_menu,
    show_message,
)
from glitter.config import AppConfig
from glitter.ui import TerminalUI


class StubUI(TerminalUI):
    def __init__(self, inputs: Iterable[str]):
        super().__init__()
        self._inputs = iter(inputs)
        self.events: list[str] = []

    def input(self, prompt):
        self.events.append(f"prompt:{prompt}")
        try:
            return next(self._inputs)
        except StopIteration:
            return ""

    def print(self, message, *, end: str = "\n"):
        self.events.append(f"print:{message}")

    def blank(self):
        self.events.append("<blank>")


class StubApp:
    def __init__(self):
        self.transfer_port = 45846
        self.default_download_dir = Path("/tmp")
        self.device_name = "tester"
        self._auto_accept_mode = "off"
        self._encryption = True

    @property
    def auto_accept_mode(self):
        return self._auto_accept_mode

    @property
    def encryption_enabled(self):
        return self._encryption

    @property
    def allows_ephemeral_fallback(self):
        return True

    def update_identity(self, device_name: str, language: str) -> None:
        self.device_name = device_name

    def change_transfer_port(self, new_port: int) -> int:
        return new_port

    def set_default_download_dir(self, path: Path) -> Path:
        self.default_download_dir = path
        return path

    def reset_default_download_dir(self) -> Path:
        self.default_download_dir = Path("/tmp/default")
        return self.default_download_dir

    def clear_trusted_fingerprints(self) -> bool:
        return True


def test_localized_argument_parser_usage_and_error():
    messages = {
        "cli_usage": "usage: %(prog)s [options]",
        "cli_usage_prefix": "Usage:",
    }
    parser = LocalizedArgumentParser(messages=messages, prog="glitter")
    usage = parser.format_usage()
    assert "Usage:" in usage
    with pytest.raises(SystemExit) as exc:
        parser.error("oops")
    assert exc.value.code == 2


def test_prompt_language_choice_blank_returns_default(monkeypatch):
    ui = StubUI(inputs=[""])
    result = prompt_language_choice(ui, default="en")
    assert result == "en"


def test_prompt_language_choice_invalid_then_valid(monkeypatch):
    ui = StubUI(inputs=["xyz", "en"])
    monkeypatch.setenv("GLITTER_DEBUG", "")  # no effect
    result = prompt_language_choice(ui, default="en")
    assert result == "en"


def test_prompt_language_choice_cancel(monkeypatch):
    class CancelUI(StubUI):
        def input(self, prompt):
            raise KeyboardInterrupt

    ui = CancelUI(inputs=[])
    with pytest.raises(SystemExit):
        prompt_language_choice(ui, default="en", allow_cancel=False)


def test_prompt_device_name_defaults_to_system(monkeypatch):
    ui = StubUI(inputs=[""])
    result = prompt_device_name(ui, "en", default_name="custom")
    assert result == "custom"


def test_settings_menu_language_and_exit(monkeypatch, tmp_path):
    ui = StubUI(inputs=["1", "fr", "10"])
    config = AppConfig()
    config.language = "en"
    config.device_name = "tester"
    app = StubApp()
    monkeypatch.setattr("glitter.cli.prompt_language_choice", lambda *args, **kwargs: "fr")
    monkeypatch.setattr("glitter.cli.prompt_device_name", lambda *args, **kwargs: "tester")
    monkeypatch.setattr("glitter.cli.save_config", lambda config: None)
    monkeypatch.setattr("glitter.cli.show_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.local_network_addresses", lambda: ["127.0.0.1"])
    result = settings_menu(ui, app, config, language="en")
    assert result == "en" or result == "fr"


def test_settings_menu_invalid_choice(monkeypatch):
    ui = StubUI(inputs=["x", "10"])
    config = AppConfig()
    app = StubApp()
    monkeypatch.setattr("glitter.cli.prompt_language_choice", lambda *_: "en")
    monkeypatch.setattr("glitter.cli.prompt_device_name", lambda *_: "tester")
    monkeypatch.setattr("glitter.cli.show_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.local_network_addresses", lambda: ["127.0.0.1"])
    monkeypatch.setattr("glitter.cli.save_config", lambda config: None)
    result = settings_menu(ui, app, config, language="en")
    assert result == "en"


def test_settings_menu_port_invalid(monkeypatch):
    ui = StubUI(inputs=["3", "notanumber", "10"])
    config = AppConfig()
    app = StubApp()
    prompts: list[str] = []
    monkeypatch.setattr("glitter.cli.prompt_language_choice", lambda *_: "en")
    monkeypatch.setattr("glitter.cli.prompt_device_name", lambda *_: "tester")
    monkeypatch.setattr("glitter.cli.show_message", lambda ui, key, lang, **kwargs: prompts.append(key))
    monkeypatch.setattr("glitter.cli.render_message", lambda key, lang, **kw: Text(key))
    monkeypatch.setattr("glitter.cli.local_network_addresses", lambda: ["127.0.0.1"])
    monkeypatch.setattr("glitter.cli.save_config", lambda config: None)
    result = settings_menu(ui, app, config, language="en")
    assert result == "en"
    assert "settings_port_invalid" in prompts
