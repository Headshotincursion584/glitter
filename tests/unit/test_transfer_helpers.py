from __future__ import annotations

from pathlib import Path

import pytest

from glitter.transfer import SendFilePayload, TransferService


def _service(tmp_path: Path) -> TransferService:
    return TransferService(
        device_id="device",
        device_name="tester",
        language="en",
        on_new_request=lambda _: None,
        allow_ephemeral_fallback=False,
    )


def test_prepare_send_file_payload_directory(tmp_path: Path) -> None:
    service = _service(tmp_path)
    directory = tmp_path / "dir"
    directory.mkdir()
    (directory / "file.txt").write_text("hello", encoding="utf-8")

    payload = service._prepare_send_file_payload(directory)

    assert payload.content_type == "directory"
    assert payload.archive_format == "zip-store"
    assert payload.original_size == 5
    assert payload.cleanup_path is not None


def test_build_sender_metadata_includes_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = _service(tmp_path)
    service._identity_public = b"identity"
    service._identity_display = "ID"
    payload = SendFilePayload(
        send_path=tmp_path / "file.bin",
        cleanup_path=None,
        filename="file.bin",
        content_type="file",
        archive_format=None,
        original_size=None,
        file_size=10,
        file_hash="abcd",
    )

    metadata = service._build_sender_metadata(payload, encrypting=True, nonce=b"n", public_key=123)

    assert metadata["identity"]["fingerprint"] == "ID"
    assert metadata["dh_public"]
    assert metadata["nonce"]


def test_evaluate_identity_status_existing_trusted(tmp_path: Path) -> None:
    store = type("Store", (), {"get": lambda self, key: type("Peer", (), {"fingerprint_hex": "abcd", "fingerprint_display": "known"})(), "touch": lambda self, key, name: None})()
    service = _service(tmp_path)
    service._trust_store = store

    status, previous, display = service._evaluate_identity_status(
        sender_id="peer",
        sender_name="peername",
        identity_public=b"pub",
        identity_hex="abcd",
        identity_display=None,
        identity_payload={"public": ""},
    )

    assert status == "trusted"
    assert previous is None
    assert display == "known"


def test_evaluate_identity_status_changed(tmp_path: Path) -> None:
    class FakeStore:
        def __init__(self) -> None:
            self._remembered = None

        def get(self, key):
            return type("Peer", (), {"fingerprint_hex": "old", "fingerprint_display": "OLD"})()

        def remember(self, *args, **kwargs):
            self._remembered = (args, kwargs)

        def touch(self, *args, **kwargs):
            pass

    store = FakeStore()
    service = _service(tmp_path)
    service._trust_store = store

    status, previous, _ = service._evaluate_identity_status(
        sender_id="peer",
        sender_name="Peer",
        identity_public=b"pub",
        identity_hex="new",
        identity_display="DISPLAY",
        identity_payload={"public": ""},
    )

    assert status == "changed"
    assert previous == "OLD"
