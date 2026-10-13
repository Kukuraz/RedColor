# RedColor — сборка установщика. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Собирает RedColor.exe (PyInstaller) и установщик RedColor_Setup_<версия>.exe (Inno Setup).

Запуск:  py -3.14 installer\\build.py
Результат: installer\\Output\\RedColor_Setup_1.1.exe
Бланки и цитаты в сборку не попадают (их нет в папке программы — они хранятся у пользователя).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("TEMP", str(ROOT))) / "RedColor_build"
DIST = WORK / "dist"
OUT = ROOT / "installer" / "Output"
ISCC = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"

EXCLUDE = [
    "tkinter", "IPython", "jupyter", "notebook", "scipy", "pandas", "PyQt5", "PyQt6", "PySide2",
    "matplotlib.backends.backend_tkagg", "matplotlib.backends.backend_qtagg", "matplotlib.backends.backend_qt5agg",
    "matplotlib.backends.backend_webagg", "matplotlib.backends.backend_nbagg",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DExtras",
    "PySide6.Qt3DAnimation", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtBluetooth", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtWebSockets",
    "PySide6.QtTest", "PySide6.QtSql", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtNfc", "PySide6.QtSpatialAudio", "PySide6.QtUiTools", "PySide6.QtOpenGLWidgets",
    "PySide6.QtWebView", "PySide6.QtAxContainer", "PySide6.QtConcurrent", "PySide6.QtDBus",
]


def main():
    if not ISCC.exists():
        sys.exit(f"Не найден Inno Setup: {ISCC}")
    shutil.rmtree(WORK, ignore_errors=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", "RedColor",
            "--icon", str(ROOT / "assets" / "redcolor.ico"),
            "--version-file", str(ROOT / "installer" / "version_info.txt"),
            "--add-data", f"{ROOT / 'assets'}{os.pathsep}assets",
            "--distpath", str(DIST), "--workpath", str(WORK / "build"), "--specpath", str(WORK),
            "--paths", str(ROOT)]
    for m in EXCLUDE:
        args += ["--exclude-module", m]
    args.append(str(ROOT / "RedColor.pyw"))
    print("PyInstaller…")
    subprocess.check_call(args, cwd=str(WORK.parent))
    app = DIST / "RedColor"
    # лишние переводы и плагины Qt, которые не нужны программе
    qt = app / "_internal" / "PySide6"
    for sub in ("translations",):
        d = qt / sub
        if d.is_dir():
            for f in d.iterdir():
                if f.is_file() and not (f.name.startswith("qtbase_ru") or f.name.startswith("qt_ru")):
                    f.unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    print("Inno Setup…")
    subprocess.check_call([str(ISCC), f"/DDistDir={app}", f"/DRootDir={ROOT}", f"/O{OUT}",
                           str(ROOT / "installer" / "RedColor.iss")])
    print("Готово:", OUT)


if __name__ == "__main__":
    main()
