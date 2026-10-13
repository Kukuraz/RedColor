# RedColor — редактор PDF для проверки работ. Автор: Maksim Belonoskin, Zelenograd, Moscow, Russia.
"""Регистрация RedColor как программы для PDF (только для текущего пользователя, HKCU)."""
import ctypes
import os
import subprocess
import sys
import winreg
from pathlib import Path

from .config import APP_DIR, ASSETS, AUTHOR, FROZEN

PROGID = "RedColor.PDF"


def pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def launcher():
    """(программа, аргументы) для запуска RedColor: установленный exe или скрипт через pythonw."""
    if FROZEN:
        return str(Path(sys.executable).resolve()), ""
    return pythonw(), f'"{APP_DIR / "RedColor.pyw"}"'


def command():
    exe, args = launcher()
    return f'"{exe}" {args} "%1"'.replace("  ", " ")


def _set(root, path, name, value):
    k = winreg.CreateKeyEx(root, path, 0, winreg.KEY_WRITE)
    winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
    winreg.CloseKey(k)


def register():
    ico = str(ASSETS / "redcolor.ico")
    H = winreg.HKEY_CURRENT_USER
    base = rf"Software\Classes\{PROGID}"
    _set(H, base, "", "Документ PDF (RedColor)")
    _set(H, base, "FriendlyTypeName", "Документ PDF")
    _set(H, base + r"\DefaultIcon", "", ico)
    _set(H, base + r"\Application", "ApplicationName", "RedColor")
    _set(H, base + r"\Application", "ApplicationIcon", ico)
    _set(H, base + r"\Application", "ApplicationDescription", "Редактор PDF для проверки работ")
    _set(H, base + r"\Application", "ApplicationCompany", AUTHOR)
    _set(H, base + r"\shell", "", "open")
    _set(H, base + r"\shell\open", "FriendlyAppName", "RedColor")
    _set(H, base + r"\shell\open\command", "", command())
    _set(H, r"Software\Classes\.pdf\OpenWithProgids", PROGID, "")
    cap = r"Software\RedColor\Capabilities"
    _set(H, cap, "ApplicationName", "RedColor")
    _set(H, cap, "ApplicationIcon", ico)
    _set(H, cap, "ApplicationDescription", "Редактор PDF для проверки работ")
    _set(H, cap + r"\FileAssociations", ".pdf", PROGID)
    _set(H, r"Software\RegisteredApplications", "RedColor", cap)
    app = "\\".join(["Software", "Classes", "Applications", "RedColor.exe" if FROZEN else "RedColor.pyw"])
    _set(H, app, "FriendlyAppName", "RedColor")
    _set(H, app + r"\DefaultIcon", "", ico)
    _set(H, app + r"\shell\open\command", "", command())
    _set(H, app + r"\SupportedTypes", ".pdf", "")
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)


def open_default_apps():
    try:
        os.startfile("ms-settings:defaultapps?registeredAppUser=RedColor")
    except OSError:
        os.startfile("ms-settings:defaultapps")


def make_shortcuts():
    """Ярлыки на рабочем столе и в меню «Пуск»."""
    ico = str(ASSETS / "redcolor.ico")
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
    targets = []
    try:
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY
        desktop = Path(buf.value)
    except Exception:
        pass
    targets.append(desktop / "RedColor.lnk")
    start = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    targets.append(start / "RedColor.lnk")
    exe, args = launcher()
    args = args.replace('"', '\\"') if args else ""
    for lnk in targets:
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
              f"$s.TargetPath='{exe}';$s.Arguments='{args}';"
              f"$s.WorkingDirectory='{Path(exe).parent if FROZEN else APP_DIR}';$s.IconLocation='{ico}';"
              f"$s.Description='RedColor — редактор PDF. {AUTHOR}';$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                       creationflags=0x08000000)
    return targets
