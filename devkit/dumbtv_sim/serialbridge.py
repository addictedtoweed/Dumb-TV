"""dumbtv_sim.serialbridge -- expose the sim's command port over TCP.

A host script (or host/dumbtv.py, pointed at a socket) connects to localhost and
speaks the exact byte protocol it would over a real UART. Received bytes are
queued; the app drains them on its main thread (so all OSD mutation stays single-
threaded) and hands back responses via send().
"""

import queue
import socket
import threading


class SerialBridge:
    def __init__(self, host="127.0.0.1", port=5555):
        self.addr = (host, port)
        self._rx = queue.Queue()
        self._clients = []
        self._lock = threading.Lock()
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(self.addr)
        self._srv.listen(4)
        self._run = True
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self._run:
            try:
                conn, _ = self._srv.accept()
            except OSError:
                break
            with self._lock:
                self._clients.append(conn)
            threading.Thread(target=self._reader, args=(conn,), daemon=True).start()

    def _reader(self, conn):
        while self._run:
            try:
                data = conn.recv(4096)
            except OSError:
                data = b""
            if not data:
                break
            self._rx.put(data)
        with self._lock:
            if conn in self._clients:
                self._clients.remove(conn)
        conn.close()

    def poll(self) -> bytes:
        """Non-blocking: all bytes received since the last poll."""
        chunks = []
        try:
            while True:
                chunks.append(self._rx.get_nowait())
        except queue.Empty:
            pass
        return b"".join(chunks)

    def send(self, data: bytes):
        if not data:
            return
        with self._lock:
            for conn in list(self._clients):
                try:
                    conn.sendall(data)
                except OSError:
                    pass

    def close(self):
        self._run = False
        try:
            self._srv.close()
        except OSError:
            pass
