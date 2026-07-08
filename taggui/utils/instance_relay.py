import json
import os
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from utils.settings import settings


IPC_LAST_SERVER_NAME_KEY = 'ipc/last_server_name'
IPC_SERVER_NAME_PREFIX = 'taggui_open_relay_v1_'


def build_instance_server_name() -> str:
    unique = uuid.uuid4().hex
    return f"{IPC_SERVER_NAME_PREFIX}{os.getpid()}_{unique}"


def remember_preferred_server_name(server_name: str):
    server_name = str(server_name or '').strip()
    if server_name:
        settings.setValue(IPC_LAST_SERVER_NAME_KEY, server_name)
        settings.sync()


def forget_preferred_server_name(server_name: str):
    server_name = str(server_name or '').strip()
    if not server_name:
        return
    current = str(settings.value(IPC_LAST_SERVER_NAME_KEY, '', type=str) or '').strip()
    if current == server_name:
        settings.setValue(IPC_LAST_SERVER_NAME_KEY, '')
        settings.sync()


def preferred_server_name() -> str:
    return str(settings.value(IPC_LAST_SERVER_NAME_KEY, '', type=str) or '').strip()


def send_open_request(
    *,
    server_name: str,
    directory_path: Path,
    select_path: str | None = None,
    timeout_ms: int = 1500,
) -> bool:
    server_name = str(server_name or '').strip()
    if not server_name:
        return False

    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        return False

    payload = {
        'command': 'open_directory',
        'directory_path': str(directory_path),
        'select_path': str(select_path) if select_path else '',
    }
    message = json.dumps(payload).encode('utf-8')
    socket.write(message)
    if not socket.waitForBytesWritten(timeout_ms):
        socket.abort()
        return False
    socket.flush()
    socket.disconnectFromServer()
    return True


class OpenRequestRelay(QObject):
    open_request_received = Signal(str, str)

    def __init__(self, server_name: str, parent=None):
        super().__init__(parent)
        self.server_name = str(server_name or '').strip()
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._buffers: dict[QLocalSocket, bytearray] = {}

    def start(self) -> bool:
        if not self.server_name:
            return False
        QLocalServer.removeServer(self.server_name)
        return self._server.listen(self.server_name)

    def stop(self):
        try:
            self._server.close()
        except Exception:
            pass
        try:
            QLocalServer.removeServer(self.server_name)
        except Exception:
            pass

    def _on_new_connection(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(lambda s=socket: self._on_disconnected(s))
            socket.errorOccurred.connect(lambda *_args, s=socket: self._on_disconnected(s))

    def _on_ready_read(self, socket: QLocalSocket):
        try:
            payload = bytes(socket.readAll())
        except Exception:
            payload = b''
        if not payload:
            return
        buffer = self._buffers.setdefault(socket, bytearray())
        buffer.extend(payload)

    def _on_disconnected(self, socket: QLocalSocket):
        buffer = bytes(self._buffers.pop(socket, bytearray()))
        try:
            socket.deleteLater()
        except Exception:
            pass
        if not buffer:
            return
        try:
            payload = json.loads(buffer.decode('utf-8'))
        except Exception:
            return
        if str(payload.get('command') or '') != 'open_directory':
            return
        directory_path = str(payload.get('directory_path') or '').strip()
        select_path = str(payload.get('select_path') or '').strip()
        if not directory_path:
            return
        self.open_request_received.emit(directory_path, select_path)
