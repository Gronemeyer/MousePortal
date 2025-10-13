"""Lightweight socket interface for MousePortal.

Provides a minimal TCP server that accepts newline-delimited JSON messages
from a parent controller process running on the same machine. Messages are
placed on a thread-safe queue for consumption by the Panda3D application and
responses can be queued back to the parent.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from queue import Queue, Empty
from typing import Any, Dict, Optional


class PortalServer:
    """Single-client JSON-over-TCP helper with timestamped messaging."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._incoming: Queue[Dict[str, Any]] = Queue()
        self._outgoing: Queue[Dict[str, Any]] = Queue()
        self._server: Optional[socket.socket] = None
        self._client: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, name="PortalSocket", daemon=True)
        self._lock = threading.Lock()
        self._recv_buffer = ""

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            if self._client:
                try:
                    self._client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._client.close()
                self._client = None
            if self._server:
                try:
                    self._server.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._server.close()
                self._server = None

    def is_client_connected(self) -> bool:
        with self._lock:
            return self._client is not None

    def get_message(self, timeout: float | None = 0.0) -> Optional[Dict[str, Any]]:
        try:
            return self._incoming.get(timeout=timeout)
        except Empty:
            return None

    def send_message(self, payload: Dict[str, Any]) -> None:
        """Queue a payload for delivery to the connected parent."""
        payload = dict(payload)
        payload.setdefault("server_time", time.time())
        self._outgoing.put(payload)

    # Internal helpers -----------------------------------------------------------------

    def _serve(self) -> None:
        try:
            self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server.bind((self.host, self.port))
            self._server.listen(1)
            self._server.settimeout(0.5)
        except OSError as exc:
            self._incoming.put({"type": "error", "message": f"socket_init_failed: {exc}", "server_time": time.time()})
            return

        while not self._stop.is_set():
            if not self.is_client_connected():
                self._accept_client()
                continue
            if not self._pump_io():
                self._drop_client()
        self._drop_client()

    def _accept_client(self) -> None:
        if not self._server:
            return
        try:
            conn, _addr = self._server.accept()
        except socket.timeout:
            return
        except OSError:
            return
        conn.setblocking(False)
        with self._lock:
            self._client = conn
            self._recv_buffer = ""
        self.send_message({"type": "connected"})

    def _drop_client(self) -> None:
        with self._lock:
            if self._client:
                try:
                    self._client.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self._client.close()
            self._client = None
            self._recv_buffer = ""

    def _pump_io(self) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            self._drain_outgoing(client)
            self._read_incoming(client)
            return True
        except OSError:
            return False

    def _drain_outgoing(self, client: socket.socket) -> None:
        while True:
            try:
                message = self._outgoing.get_nowait()
            except Empty:
                break
            data = json.dumps(message) + "\n"
            client.sendall(data.encode("utf-8"))

    def _read_incoming(self, client: socket.socket) -> None:
        try:
            chunk = client.recv(4096)
        except BlockingIOError:
            return
        if not chunk:
            raise OSError("client disconnected")
        self._recv_buffer += chunk.decode("utf-8", errors="ignore")
        while "\n" in self._recv_buffer:
            line, self._recv_buffer = self._recv_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            self._incoming.put({"type": "error", "message": "malformed_json", "raw": line, "server_time": time.time()})
            return
        if isinstance(message, dict):
            message.setdefault("server_time", time.time())
            self._incoming.put(message)
        else:
            self._incoming.put({"type": "error", "message": "invalid_message_type", "raw": message, "server_time": time.time()})
