"""
Application orchestration layer shared by the CLI.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional, Union

from . import __version__
from .discovery import DiscoveryService, PeerInfo
from .history import HistoryRecord, append_record, now_iso
from .language import render_message
from .transfer import (
    DEFAULT_TRANSFER_PORT,
    TransferService,
    TransferTicket,
)
from .trust import TrustedPeerStore
from .ui import TerminalUI, show_message
from .utils import ensure_download_dir


class GlitterApp:
    """Orchestrates discovery, transfers, and CLI prompts."""

    def __init__(
        self,
        device_id: str,
        device_name: str,
        language: str,
        default_download_dir: Optional[Path] = None,
        transfer_port: Optional[int] = None,
        debug: bool = False,
        encryption_enabled: bool = True,
        identity_public: Optional[bytes] = None,
        trust_store: Optional[TrustedPeerStore] = None,
        auto_accept_trusted: Union[bool, str] = False,
        ui: Optional[TerminalUI] = None,
    ) -> None:
        self.device_id = device_id
        self.device_name = device_name
        self.language = language
        self.default_download_dir = self._prepare_download_dir(default_download_dir)
        self.debug = debug
        self._encryption_enabled = encryption_enabled
        self.ui = ui or TerminalUI()
        self._identity_public = identity_public or b""
        self._trust_store = trust_store
        self._manual_peer_ids: dict[str, str] = {}
        self._manual_peer_lock = threading.Lock()
        self._auto_accept_mode = "off"
        self.set_auto_accept_mode(auto_accept_trusted)
        self._auto_reject_untrusted = False

        if isinstance(transfer_port, int) and 1 <= transfer_port <= 65535:
            preferred_port = transfer_port
            allow_fallback = False
        else:
            preferred_port = DEFAULT_TRANSFER_PORT
            allow_fallback = True

        self._preferred_port = preferred_port
        self._allow_ephemeral_fallback = allow_fallback
        self._transfer_service = self._create_transfer_service(preferred_port, allow_fallback)
        self._discovery: Optional[DiscoveryService] = None
        self._incoming_lock = threading.Lock()
        self._incoming_counter = 0
        self._history_lock = threading.Lock()

    def _prepare_download_dir(self, directory: Optional[Path]) -> Path:
        if directory is None:
            return ensure_download_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ensure_download_dir()
        return directory

    def set_default_download_dir(self, directory: Path) -> Path:
        directory = directory.expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        self.default_download_dir = directory
        return directory

    def reset_default_download_dir(self) -> Path:
        self.default_download_dir = ensure_download_dir()
        return self.default_download_dir

    @property
    def auto_accept_mode(self) -> str:
        return self._auto_accept_mode

    @property
    def auto_accept_trusted(self) -> bool:
        return self._auto_accept_mode in {"trusted", "all"}

    def set_auto_accept_mode(self, mode: Union[bool, str]) -> None:
        if isinstance(mode, bool):
            normalized = "trusted" if mode else "off"
        elif isinstance(mode, str):
            normalized = mode.strip().lower()
        else:
            normalized = "off"
        if normalized not in {"off", "trusted", "all"}:
            normalized = "off"
        self._auto_accept_mode = normalized

    def set_auto_accept_trusted(self, enabled: bool) -> None:
        self.set_auto_accept_mode("trusted" if enabled else "off")

    def set_auto_reject_untrusted(self, enabled: bool) -> None:
        self._auto_reject_untrusted = bool(enabled)

    def _create_transfer_service(self, bind_port: int, allow_fallback: bool) -> TransferService:
        return TransferService(
            device_id=self.device_id,
            device_name=self.device_name,
            language=self.language,
            on_new_request=self._handle_incoming_request,
            on_cancelled_request=self._handle_request_cancelled,
            bind_port=bind_port,
            allow_ephemeral_fallback=allow_fallback,
            encryption_enabled=self._encryption_enabled,
            identity_public=self._identity_public,
            trust_store=self._trust_store,
        )

    @property
    def transfer_port(self) -> int:
        return self._transfer_service.port

    @property
    def allows_ephemeral_fallback(self) -> bool:
        return self._allow_ephemeral_fallback

    @property
    def encryption_enabled(self) -> bool:
        return self._encryption_enabled

    def set_encryption_enabled(self, enabled: bool) -> None:
        self._encryption_enabled = bool(enabled)
        self._transfer_service.set_encryption_enabled(self._encryption_enabled)

    def identity_fingerprint(self) -> Optional[str]:
        return self._transfer_service.get_identity_fingerprint()

    def should_show_local_fingerprint(self, peer: PeerInfo) -> bool:
        if not self._trust_store:
            return True
        peer_id = getattr(peer, "peer_id", None)
        if not isinstance(peer_id, str) or not peer_id:
            return True
        return self._trust_store.get(peer_id) is None

    def cached_peer_id_for_ip(self, ip: str) -> Optional[str]:
        with self._manual_peer_lock:
            return self._manual_peer_ids.get(ip)

    def remember_peer_id_for_ip(self, ip: str, peer_id: str) -> None:
        if not peer_id:
            return
        with self._manual_peer_lock:
            self._manual_peer_ids[ip] = peer_id

    def clear_trusted_fingerprints(self) -> bool:
        if not self._trust_store:
            return False
        return self._trust_store.clear()

    def change_transfer_port(self, new_port: int) -> int:
        if not (1 <= new_port <= 65535):
            raise ValueError("invalid port")
        if new_port == self._transfer_service.port and not self._allow_ephemeral_fallback:
            return self._transfer_service.port

        self.cancel_pending_requests()
        old_service = self._transfer_service
        old_allow_fallback = self._allow_ephemeral_fallback
        old_preferred = self._preferred_port

        old_service.stop()
        try:
            new_service = self._create_transfer_service(new_port, allow_fallback=False)
            new_service.start()
        except OSError as exc:
            try:
                old_service.start()
                old_service.update_identity(self.device_name, self.language)
                if self._discovery:
                    self._discovery.update_identity(
                        self.device_name,
                        self.language,
                        old_service.port,
                    )
            finally:
                self._transfer_service = old_service
                self._allow_ephemeral_fallback = old_allow_fallback
                self._preferred_port = old_preferred
            raise exc

        new_service.update_identity(self.device_name, self.language)
        self._transfer_service = new_service
        self._preferred_port = new_port
        self._allow_ephemeral_fallback = False
        if self._discovery:
            self._discovery.update_identity(
                self.device_name,
                self.language,
                self._transfer_service.port,
            )
        return self._transfer_service.port

    def start(self) -> None:
        self._transfer_service.start()
        self._transfer_service.update_identity(self.device_name, self.language)
        self._discovery = DiscoveryService(
            peer_id=self.device_id,
            device_name=self.device_name,
            language=self.language,
            transfer_port=self._transfer_service.port,
        )
        self._discovery.start()

    def stop(self) -> None:
        try:
            if self._discovery:
                self._discovery.stop()
        except KeyboardInterrupt:
            pass
        finally:
            self._discovery = None
        try:
            self._transfer_service.stop()
        except KeyboardInterrupt:
            pass

    # Discovery --------------------------------------------------------

    def list_peers(self) -> list[PeerInfo]:
        if not self._discovery:
            return []
        return self._discovery.get_peers()

    # Transfers --------------------------------------------------------

    def send_file(
        self,
        peer: PeerInfo,
        file_path: Path,
        progress_cb: Optional[Callable[[int, int], None]] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> tuple[str, str, Optional[str]]:
        return self._transfer_service.send_file(
            peer.ip,
            peer.transfer_port,
            peer.name,
            file_path,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
        )

    def pending_requests(self) -> list[TransferTicket]:
        return self._transfer_service.pending_requests()

    def accept_request(self, request_id: str, directory: Path) -> Optional[TransferTicket]:
        directory = directory.expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        return self._transfer_service.accept_request(request_id, directory)

    def decline_request(self, request_id: str) -> bool:
        return self._transfer_service.decline_request(request_id)

    def cancel_pending_requests(self, status: str = "cancelled") -> None:
        tickets = self.pending_requests()
        if not tickets:
            return
        for ticket in tickets:
            if self._transfer_service.decline_request(ticket.request_id):
                display_name = ticket.filename + ("/" if ticket.content_type == "directory" else "")
                self.log_history(
                    direction="receive",
                    status=status,
                    filename=display_name,
                    size=ticket.filesize,
                    sha256=ticket.expected_hash,
                    remote_name=ticket.sender_name,
                    remote_ip=ticket.sender_ip,
                    source_path=None,
                    target_path=None,
                    remote_version=ticket.sender_version,
                )

    def log_history(
        self,
        direction: str,
        status: str,
        filename: str,
        size: int,
        sha256: Optional[str],
        remote_name: str,
        remote_ip: str,
        source_path: Optional[Path] = None,
        target_path: Optional[Path] = None,
        remote_version: Optional[str] = None,
    ) -> None:
        record = HistoryRecord(
            timestamp=now_iso(),
            direction=direction,
            status=status,
            filename=filename,
            size=size,
            sha256=sha256,
            local_device=self.device_name,
            remote_name=remote_name,
            remote_ip=remote_ip,
            source_path=str(source_path) if source_path else None,
            target_path=str(target_path) if target_path else None,
            local_version=__version__,
            remote_version=remote_version,
        )
        with self._history_lock:
            append_record(record)

    # Internal callbacks -----------------------------------------------

    def update_identity(self, device_name: str, language: str) -> None:
        self.device_name = device_name
        self.language = language
        self._transfer_service.update_identity(device_name, language)
        if self._discovery:
            self._discovery.update_identity(device_name, language, self._transfer_service.port)

    def _handle_incoming_request(self, ticket: TransferTicket) -> None:
        with self._incoming_lock:
            self._incoming_counter += 1
        display_name = ticket.filename + ("/" if ticket.content_type == "directory" else "")
        message = render_message(
            "incoming_notice",
            self.language,
            filename=display_name,
            size=ticket.filesize,
            name=ticket.sender_name,
            ip=ticket.sender_ip,
        )
        self.ui.blank()
        self.ui.print(message)
        self.ui.blank()
        self.ui.flush()
        if ticket.sender_version and ticket.sender_version != __version__:
            self.ui.print(
                render_message(
                    "incoming_version_warning",
                    self.language,
                    version=ticket.sender_version,
                    current=__version__,
                )
            )
            self.ui.flush()

        mode = self.auto_accept_mode
        allow_auto = mode == "all" or (mode == "trusted" and ticket.identity_status == "trusted")
        if allow_auto:
            if self._transfer_service.has_active_receiving():
                self.ui.print(
                    render_message(
                        "auto_accept_trusted_busy",
                        self.language,
                        filename=display_name,
                    )
                )
                self.ui.flush()
            else:
                destination = self.default_download_dir
                try:
                    accepted_ticket = self.accept_request(ticket.request_id, destination)
                except Exception as exc:  # noqa: BLE001
                    self.ui.print(
                        render_message(
                            "auto_accept_trusted_failed",
                            self.language,
                            error=str(exc),
                        )
                    )
                    self.ui.flush()
                else:
                    if accepted_ticket:
                        notice_key = (
                            "auto_accept_trusted_notice"
                            if ticket.identity_status == "trusted"
                            else "auto_accept_all_notice"
                        )
                        self._run_auto_accept_postprocess(
                            accepted_ticket,
                            ticket,
                            destination,
                            notice_key,
                        )
                        return
        if (
            mode == "trusted"
            and ticket.identity_status != "trusted"
            and self._auto_reject_untrusted
        ):
            self.ui.print(
                render_message(
                    "auto_accept_trusted_rejected",
                    self.language,
                    name=ticket.sender_name,
                    ip=ticket.sender_ip,
                    filename=display_name,
                )
            )
            self.ui.flush()
            self.decline_request(ticket.request_id)
        else:
            show_message(self.ui, "waiting_for_decision", self.language)
            self.ui.flush()

    def _run_auto_accept_postprocess(
        self,
        accepted_ticket: TransferTicket,
        ticket: TransferTicket,
        destination: Path,
        notice_key: str,
    ) -> None:
        display_name = ticket.filename + ("/" if ticket.content_type == "directory" else "")
        self.ui.print(
            render_message(
                notice_key,
                self.language,
                filename=display_name,
                name=ticket.sender_name,
                path=str(destination),
            )
        )
        self.ui.flush()

        def monitor_completion() -> None:
            while accepted_ticket.status in {"pending", "receiving"}:
                time.sleep(0.2)
            if accepted_ticket.status == "completed" and accepted_ticket.saved_path:
                self.log_history(
                    direction="receive",
                    status="completed",
                    filename=display_name,
                    size=accepted_ticket.filesize,
                    sha256=accepted_ticket.expected_hash,
                    remote_name=accepted_ticket.sender_name,
                    remote_ip=accepted_ticket.sender_ip,
                    source_path=None,
                    target_path=accepted_ticket.saved_path,
                    remote_version=accepted_ticket.sender_version,
                )
                self.ui.print(
                    render_message(
                        "receive_done",
                        self.language,
                        path=str(accepted_ticket.saved_path),
                    )
                )
            elif accepted_ticket.status == "failed":
                error_text = accepted_ticket.error or "failed"
                self.log_history(
                    direction="receive",
                    status=error_text,
                    filename=display_name,
                    size=accepted_ticket.filesize,
                    sha256=accepted_ticket.expected_hash,
                    remote_name=accepted_ticket.sender_name,
                    remote_ip=accepted_ticket.sender_ip,
                    source_path=None,
                    target_path=accepted_ticket.saved_path,
                    remote_version=accepted_ticket.sender_version,
                )
                self.ui.print(
                    render_message(
                        "receive_failed",
                        self.language,
                        error=error_text,
                    )
                )
            self.ui.flush()

        threading.Thread(target=monitor_completion, name="glitter-auto-accept", daemon=True).start()

    def _handle_request_cancelled(self, ticket: TransferTicket) -> None:
        display_name = ticket.filename + ("/" if ticket.content_type == "directory" else "")
        message = render_message(
            "incoming_cancelled",
            self.language,
            filename=display_name,
            name=ticket.sender_name,
        )
        self.ui.blank()
        self.ui.print(message)
        self.ui.blank()
        self.ui.flush()
        self.log_history(
            direction="receive",
            status="cancelled",
            filename=display_name,
            size=ticket.filesize,
            sha256=ticket.expected_hash,
            remote_name=ticket.sender_name,
            remote_ip=ticket.sender_ip,
            source_path=None,
            target_path=None,
            remote_version=ticket.sender_version,
        )

    def incoming_count(self) -> int:
        with self._incoming_lock:
            return self._incoming_counter

    def reset_incoming_count(self) -> None:
        with self._incoming_lock:
            self._incoming_counter = 0


__all__ = ["GlitterApp"]
