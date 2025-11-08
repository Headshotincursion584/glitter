"""Unit tests for CLI parsing helpers."""

from __future__ import annotations

import pytest

from glitter.cli import normalize_auto_accept_mode, parse_target_spec


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, None),
        ("", None),
        ("TrUsTeD", "trusted"),
        ("ALL", "all"),
        ("0", "off"),
        ("关闭", "off"),
        ("是", "trusted"),
        ("2", "all"),
    ],
)
def test_normalize_auto_accept_mode(value, expected):
    assert normalize_auto_accept_mode(value) == expected


def test_parse_target_spec_ipv4_with_port():
    result = parse_target_spec("192.168.1.5:5000", default_port=45846)
    assert result == {
        "ip": "192.168.1.5",
        "port": 5000,
        "display": "192.168.1.5:5000",
        "normalized_ip": "192.168.1.5",
    }


def test_parse_target_spec_ipv6_brackets():
    result = parse_target_spec("[2001:db8::1]:6000", default_port=45846)
    assert result["ip"] == "2001:db8::1"
    assert result["port"] == 6000
    assert result["normalized_ip"] == "2001:db8::1"


def test_parse_target_spec_defaults_to_port_when_missing():
    result = parse_target_spec("10.0.0.8", default_port=1234)
    assert result["port"] == 1234


@pytest.mark.parametrize(
    "text",
    [
        "not-an-ip",
        "[2001:db8::1",
        "10.0.0.1:99999",
        "[]:1234",
    ],
)
def test_parse_target_spec_invalid_inputs(text):
    assert parse_target_spec(text, default_port=45846) is None
