from __future__ import annotations

import io
import json
import socket
from pathlib import Path

import pytest

from glitter.security import encode_bytes
from glitter.transfer import TransferService


def _make_metadata(**overrides: object) -> str:
    base = {
        "type": "transfer",
        "protocol": 2,
        "request_id": "req",
        "filename": "incoming.bin",
        "filesize": 0,
        "sender_name": "Peer",
        "sender_language": "en",
        "sha256": "deadbeef",
        "content_type": "file",
        "encryption": "enabled",
        "nonce": encode_bytes(b"1234567890abcdef"),
        "dh_public": encode_bytes((2).to_bytes(1, "big")),
    }
    base.update(overrides)
    return json.dumps(base) + "\n"


class FakeConn:
    def __init__(self, metadata: str, peek_empty: bool = False):
        self._metadata = metadata.encode("utf-8")
        self.sent: list[bytes] = []
        self._peek_empty = peek_empty
        self._peek_called = False

    def makefile(self, mode: str):
        return io.BytesIO(self._metadata)

    def settimeout(self, _):
        pass

    def setsockopt(self, *args, **kwargs):
        pass

    def recv(self, *_args, flags=0):
        if flags & socket.MSG_PEEK:
            if self._peek_empty and not self._peek_called:
                self._peek_called = True
                return b""
            raise socket.timeout
        return b""

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def shutdown(self, *_) -> None:
        pass

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class CaptureService(TransferService):
    def __init__(self):
        super().__init__(
            device_id="device",
            device_name="tester",
            language="en",
            on_new_request=lambda ticket: None,
            allow_ephemeral_fallback=False,
        )
        self.sent: list[str] = []


@pytest.mark.parametrize(
    "metadata,reason",
    [
        (_make_metadata(encryption="disabled"), "encryption"),
        ("{}\n", "type"),
    ],
)
def test_handle_client_declines_on_missing_requirements(
    monkeypatch: pytest.MonkeyPatch, metadata: str, reason: str
) -> None:
    service = CaptureService()

    def fake_sendline(_, text):
        service.sent.append(text)

    monkeypatch.setattr("glitter.transfer._sendline", fake_sendline)

    if reason == "type":
        conn = FakeConn(metadata)
        service._handle_client(conn, ("1.1.1.1", 1234))
        assert not service.sent or service.sent[-1].startswith("DECLINE")
        return

    conn = FakeConn(metadata)
    service._handle_client(conn, ("1.1.1.1", 1234))
    assert any("DECLINE" in line for line in service.sent)


def test_handle_client_declines_when_missing_nonce(monkeypatch: pytest.MonkeyPatch) -> None:
    service = CaptureService()
    monkeypatch.setattr("glitter.transfer._sendline", lambda *_: service.sent.append("DECLINE"))
    conn = FakeConn(_make_metadata(nonce=""))
    service._handle_client(conn, ("2.2.2.2", 4321))
    assert any("DECLINE" in line for line in service.sent)


def test_handle_client_declines_when_missing_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    service = CaptureService()
    metadata = json.loads(_make_metadata())
    metadata.pop("sha256", None)
    conn = FakeConn(json.dumps(metadata) + "\n")
    monkeypatch.setattr("glitter.transfer._sendline", lambda *_: service.sent.append("DECLINE"))
    service._handle_client(conn, ("5.5.5.5", 5555))
    assert any("DECLINE" in line for line in service.sent)


def test_handle_client_declines_on_bad_dh(monkeypatch: pytest.MonkeyPatch) -> None:
    service = CaptureService()
    monkeypatch.setattr("glitter.transfer._sendline", lambda *_: service.sent.append("DECLINE"))
    conn = FakeConn(_make_metadata(dh_public="$$invalid$$"))
    service._handle_client(conn, ("3.3.3.3", 1111))
    assert any("DECLINE" in line for line in service.sent)


def test_handle_client_triggers_cancelled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    records: list[str] = []
    cancelled: list[TransferService] = []

    def on_cancel(ticket):
        cancelled.append(ticket)

    service = TransferService(
        device_id="device",
        device_name="tester",
        language="en",
        on_new_request=lambda _: records.append("new"),
        on_cancelled_request=on_cancel,
        allow_ephemeral_fallback=False,
    )
    conn = FakeConn(_make_metadata(), peek_empty=True)
    service._handle_client(conn, ("4.4.4.4", 2222))
    assert cancelled
