import hashlib

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    showRequested = Signal()

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        digest = hashlib.sha256(key.encode("utf-8", "strict")).hexdigest()[:24]
        self._name = "scripture-single-instance-" + digest
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_new_connection)

    def acquire(self) -> bool:
        probe = QLocalSocket()
        probe.connectToServer(self._name)
        if probe.waitForConnected(150):
            probe.write(b"show\n")
            probe.flush()
            probe.waitForBytesWritten(150)
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            raise RuntimeError(self._server.errorString())
        return True

    def _on_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            if connection is None:
                continue
            connection.readyRead.connect(lambda c=connection: self._on_ready(c))
            connection.disconnected.connect(connection.deleteLater)
            self._on_ready(connection)

    def _on_ready(self, connection: QLocalSocket) -> None:
        if b"show" in bytes(connection.read(4096)):
            self.showRequested.emit()
            connection.disconnectFromServer()
