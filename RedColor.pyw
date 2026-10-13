# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""RedColor — редактор PDF для проверки работ. Запуск: двойной щелчок по этому файлу или ярлыку."""
import os
import sys
import traceback

APP = os.path.dirname(os.path.abspath(__file__))
if APP not in sys.path:
    sys.path.insert(0, APP)


def _log_path():
    base = os.path.join(os.environ.get("APPDATA", APP), "RedColor")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "log.txt")


def main():
    if sys.stderr is None or sys.executable.lower().endswith("pythonw.exe"):
        f = open(_log_path(), "a", encoding="utf-8", buffering=1)
        sys.stderr = f
        sys.stdout = f
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("RedColor.App")
    except Exception:
        pass
    from PySide6.QtCore import QByteArray, Qt, QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    files = [a for a in sys.argv[1:] if not a.startswith("-")]
    # один экземпляр программы на пользователя; REDCOLOR_INSTANCE — отдельный экземпляр (для проверки сборки)
    name = "RedColor-" + os.environ.get("REDCOLOR_INSTANCE", os.environ.get("USERNAME", "user"))
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(300):
        sock.write(("\n".join(os.path.abspath(f) for f in files) or "\x00").encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("RedColor")
    app.setOrganizationName("RedColor")
    from rp.config import ASSETS
    app.setWindowIcon(QIcon(str(ASSETS / "redcolor.ico")))
    from rp import fonts
    fonts.init()
    from rp.theme import qss
    app.setStyleSheet(qss())
    from rp.render import service
    service()
    from rp.mainwindow import MainWindow
    w = MainWindow()

    def excepthook(t, v, tb):
        msg = "".join(traceback.format_exception(t, v, tb))
        print(msg, file=sys.stderr)
        try:
            w.toast.show_msg("Ошибка: " + str(v)[:160], 5000)
        except Exception:
            pass
    sys.excepthook = excepthook

    server = QLocalServer()
    QLocalServer.removeServer(name)
    server.listen(name)

    def incoming():
        c = server.nextPendingConnection()
        if c is None:
            return

        def read():
            data = bytes(c.readAll()).decode("utf-8", "replace")
            paths = [p for p in data.split("\n") if p.strip() and p != "\x00"]
            if paths:
                w.open_paths(paths)
            w.setWindowState((w.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
            w.show()
            w.raise_()
            w.activateWindow()
        c.readyRead.connect(read)
    server.newConnection.connect(incoming)

    w.show()
    if files:
        QTimer.singleShot(0, lambda: w.open_paths(files))
    return app.exec()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main() or 0)
