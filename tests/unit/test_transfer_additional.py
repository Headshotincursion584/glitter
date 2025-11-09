"""
Tests for transfer helper coverage:
- transfer ticket lifecycle and cancellation handling
- networking/metadata helper parsing paths
- archive creation/extraction and security checks
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from glitter.transfer import _readline, TransferCancelled, TransferService, TransferTicket


def _make_service() -> TransferService:
    return TransferService(
        device_id="device",
        device_name="tester",
        language="en",
        on_new_request=lambda _: None,
        allow_ephemeral_fallback=False,
    )


def test_readline_raises_when_empty() -> None:
    class EmptyReader:
        def readline(self) -> bytes:
            return b""

    with pytest.raises(ConnectionError):
        _readline(EmptyReader())


def test_transfer_ticket_wait_for_decision_requires_setting() -> None:
    ticket = TransferTicket(
        request_id="ticket",
        filename="file",
        filesize=1,
        sender_name="peer",
        sender_ip="127.0.0.1",
        sender_language="en",
    )
    ticket._event.set()
    with pytest.raises(RuntimeError):
        ticket.wait_for_decision()

    ticket.decline()
    assert ticket._decision == "decline"
    assert ticket._event.is_set()


def test_transfer_cancelled_stores_hash() -> None:
    exc = TransferCancelled("abc123")
    assert exc.file_hash == "abc123"


def test_configure_incoming_socket_ignores_errors() -> None:
    class BrokenSocket:
        def setsockopt(self, *args, **kwargs):
            raise OSError

    TransferService._configure_incoming_socket(BrokenSocket())


def test_read_transfer_metadata_handles_bad_input() -> None:
    class Reader:
        def readline(self):
            raise ConnectionError

    assert TransferService._read_transfer_metadata(Reader()) is None

    assert TransferService._read_transfer_metadata(io.BytesIO(b"not-json\n")) is None
    assert TransferService._read_transfer_metadata(io.BytesIO(b'{"type":"other"}\n')) is None


def test_parse_identity_payload_uses_fingerprint_only() -> None:
    result = TransferService._parse_identity_payload({"fingerprint": "SUMMARY"})
    assert result == (None, "SUMMARY", None)


def test_evaluate_identity_status_remembers_new_peer(tmp_path: Path) -> None:
    remembered: list[tuple[str, str, bytes, str, str]] = []

    class StubStore:
        def get(self, key: str):
            return None

        def remember(self, peer_id: str, name: str, public_key: bytes, display: str, fingerprint_hex: str):
            remembered.append((peer_id, name, public_key, display, fingerprint_hex))

        def touch(self, *args, **kwargs):
            raise AssertionError("touch should not be called")

    service = _make_service()
    service._trust_store = StubStore()

    status, previous, display = service._evaluate_identity_status(
        sender_id="peer",
        sender_name="Peer",
        identity_public=b"bytes",
        identity_hex="abcd",
        identity_display="ID",
        identity_payload={"public": ""},
    )

    assert status == "new"
    assert previous is None
    assert display == "ID"
    assert remembered
    assert remembered[0][0] == "peer"


def test_evaluate_identity_status_unknown_without_keys() -> None:
    service = _make_service()

    status, previous, display = service._evaluate_identity_status(
        sender_id=None,
        sender_name="Peer",
        identity_public=None,
        identity_hex=None,
        identity_display=None,
        identity_payload={"public": ""},
    )

    assert status == "unknown"
    assert previous is None
    assert display is None


def test_accept_and_decline_request(tmp_path: Path) -> None:
    service = _make_service()
    ticket = TransferTicket(
        request_id="one",
        filename="file",
        filesize=1,
        sender_name="peer",
        sender_ip="127.0.0.1",
        sender_language="en",
    )
    service._pending[ticket.request_id] = ticket

    assert service.accept_request("missing", tmp_path) is None
    assert service.decline_request("missing") is False

    result = service.accept_request(ticket.request_id, tmp_path / "dest")
    assert result is ticket
    assert ticket._decision == "accept"

    service._pending[ticket.request_id] = ticket
    assert service.decline_request(ticket.request_id) is True
    assert ticket._decision == "decline"


def test_create_zip_from_directory_records_empty(tmp_path: Path) -> None:
    service = _make_service()
    base = tmp_path / "source"
    base.mkdir()
    (base / "sub").mkdir()
    file_path = base / "file.txt"
    file_path.write_text("payload", encoding="utf-8")

    archive_path, total = service._create_zip_from_directory(base)

    assert archive_path.exists()
    assert total == file_path.stat().st_size
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
    assert any(name.endswith("/") for name in names)


def test_extract_directory_archive_detects_zip_slip(tmp_path: Path) -> None:
    archive_path = tmp_path / "escape.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../evil.txt", "pwned")

    service = _make_service()
    with pytest.raises(ValueError):
        service._extract_directory_archive(archive_path, tmp_path / "dest")


def test_extract_directory_archive_extracts_files(tmp_path: Path) -> None:
    archive_path = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("inner.txt", "ok")

    service = _make_service()
    dest = tmp_path / "out"
    service._extract_directory_archive(archive_path, dest)
    assert (dest / "inner.txt").read_text(encoding="utf-8") == "ok"


def test_zip_helpers_handle_directories(tmp_path: Path) -> None:
    temp_zip = tmp_path / "temp.zip"
    added: set[str] = set()
    with zipfile.ZipFile(temp_zip, "w") as archive:
        TransferService._add_zip_directory_entry(archive, added, Path("."))
        TransferService._add_zip_directory_entry(archive, added, Path("child"))
        TransferService._add_zip_directory_entry(archive, added, Path("child"))

    assert added == {"child/"}
    assert TransferService._zip_arcname(Path("one/two")) == "one/two"
