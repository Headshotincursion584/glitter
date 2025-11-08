"""Local firewall probing helpers."""

from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from typing import Optional, Tuple


LoopbackAddress = "127.0.0.1"


@dataclass
class FirewallProbeResult:
    """Represents the outcome of the TCP/UDP firewall probe."""

    tcp_ok: bool
    udp_ok: bool
    tcp_error: Optional[str] = None
    udp_error: Optional[str] = None


ProbeOutcome = Tuple[bool, Optional[str]]


def probe_local_ports(tcp_port: int, udp_port: int, *, timeout: float = 0.75) -> FirewallProbeResult:
    """Check whether loopback TCP/UDP traffic can reach the given ports."""

    tcp_ok, tcp_error = _probe_tcp_port(tcp_port, timeout)
    udp_ok, udp_error = _probe_udp_port(udp_port, timeout)
    return FirewallProbeResult(tcp_ok=tcp_ok, udp_ok=udp_ok, tcp_error=tcp_error, udp_error=udp_error)


def _probe_tcp_port(port: int, timeout: float) -> ProbeOutcome:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("", port))
        listener.listen(1)
    except OSError as exc:  # Port already in use / permission denied
        listener.close()
        return False, f"bind failed: {exc}"

    actual_port = listener.getsockname()[1]
    accept_done = threading.Event()
    result: dict[str, Optional[str]] = {"error": None}
    success = {"value": False}

    def _accept_once() -> None:
        try:
            listener.settimeout(timeout)
            conn, _ = listener.accept()
        except OSError as exc:
            result["error"] = f"accept failed: {exc}"
            return
        else:
            with conn:
                success["value"] = True
        finally:
            accept_done.set()
            listener.close()

    thread = threading.Thread(target=_accept_once, name="glitter-firewall-tcp", daemon=True)
    thread.start()
    try:
        with socket.create_connection((LoopbackAddress, actual_port), timeout=timeout) as sock:
            try:
                sock.sendall(b"\0")
            except OSError:
                pass
    except OSError as exc:
        result["error"] = f"connect failed: {exc}"
        listener.close()
        accept_done.set()

    if not accept_done.wait(timeout):
        result["error"] = result["error"] or "timeout"
    thread.join(timeout=0.05)
    return success["value"], result["error"]


def _probe_udp_port(port: int, timeout: float) -> ProbeOutcome:
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("", port))
    except OSError as exc:
        listener.close()
        return False, f"bind failed: {exc}"

    actual_port = listener.getsockname()[1]
    recv_done = threading.Event()
    result: dict[str, Optional[str]] = {"error": None}
    success = {"value": False}

    def _recv_once() -> None:
        try:
            listener.settimeout(timeout)
            data, _ = listener.recvfrom(32)
            if data is not None:
                success["value"] = True
        except OSError as exc:
            result["error"] = f"recv failed: {exc}"
        finally:
            recv_done.set()
            listener.close()

    thread = threading.Thread(target=_recv_once, name="glitter-firewall-udp", daemon=True)
    thread.start()
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sender.settimeout(timeout)
            sender.sendto(b"ping", (LoopbackAddress, actual_port))
        finally:
            sender.close()
    except OSError as exc:
        result["error"] = f"send failed: {exc}"
        listener.close()
        recv_done.set()

    if not recv_done.wait(timeout):
        result["error"] = result["error"] or "timeout"
    thread.join(timeout=0.05)
    return success["value"], result["error"]


__all__ = ["FirewallProbeResult", "probe_local_ports"]
