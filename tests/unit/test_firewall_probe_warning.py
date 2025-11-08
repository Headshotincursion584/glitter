"""Tests for the interactive firewall probe warning helper."""

from __future__ import annotations

from types import SimpleNamespace

import glitter.cli as cli


class DummyUI:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, message, *, end: str = "\n") -> None:  # noqa: D401 - testing helper
        self.messages.append(str(message))


def _make_config(port: int = 45846) -> SimpleNamespace:
    return SimpleNamespace(transfer_port=port)


def test_firewall_warning_prints_without_detail_in_normal_mode(monkeypatch):
    ui = DummyUI()
    config = _make_config()
    result = cli.FirewallProbeResult(tcp_ok=False, udp_ok=True, tcp_error="bind failed", udp_error=None)
    monkeypatch.setattr(cli, "probe_local_ports", lambda *_, **__: result)

    cli.maybe_show_firewall_warning(ui, "en", config, debug=False)

    assert len(ui.messages) == 1
    assert "Firewall" in ui.messages[0] or "firewall" in ui.messages[0].lower()


def test_firewall_warning_quiet_when_ports_ok(monkeypatch):
    ui = DummyUI()
    config = _make_config()
    result = cli.FirewallProbeResult(tcp_ok=True, udp_ok=True)

    def _probe(*_, **__):
        return result

    monkeypatch.setattr(cli, "probe_local_ports", _probe)

    cli.maybe_show_firewall_warning(ui, "en", config, debug=False)

    assert ui.messages == []


def test_firewall_warning_shows_detail_in_debug(monkeypatch):
    ui = DummyUI()
    config = _make_config()
    result = cli.FirewallProbeResult(tcp_ok=False, udp_ok=False, tcp_error="bind failed", udp_error="timeout")
    monkeypatch.setattr(cli, "probe_local_ports", lambda *_, **__: result)

    cli.maybe_show_firewall_warning(ui, "en", config, debug=True)

    assert len(ui.messages) == 2
    assert "Details" in ui.messages[1]
