"""
Runs the app in the background, with an icon in the Windows tray (next to the clock).

Start it by double-clicking start.bat (or the VersiDen shortcut, once added). Right-click the
tray icon for: Open · Phone access · Restart · Show log · Add to Desktop and Start menu ·
Start with Windows · Quit

The app itself (app.py) runs as a hidden background process; everything it prints goes
to logs/app.log (use "Show log" in the tray menu).
"""

import json
import os
import subprocess
import sys
import threading
import time
import tomllib
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
import launcher  # noqa: E402  (shortcuts, app window, LM Studio)
LOG_DIR = BASE / "logs"
LOG_FILE = LOG_DIR / "app.log"
TRAY_LOG = LOG_DIR / "tray.log"
IS_WINDOWS = os.name == "nt"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"   # "start with Windows" (just for you, no admin)
RUN_NAME = "VersiDen"
OLD_RUN_NAMES = ("RoleplayApp",)   # earlier versions


# ------------------------------------------------------------------ settings from config.toml
def config():
    cfg = {"port": 5000, "pc_address": "versiden.localhost", "app_name": "VersiDen"}
    try:
        cfg.update(tomllib.loads((BASE / "config.toml").read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError):
        pass  # app.py creates config.toml on its first start
    return cfg


def launch_prefs():
    """Launcher choices from the Settings page (stored with the model settings)."""
    c = config()
    prefs = dict(launcher.LAUNCH_DEFAULTS)
    try:
        saved = json.loads((BASE / c.get("worlds_dir", "worlds") / ".settings.json").read_text(encoding="utf-8"))
        prefs.update({k: saved[k] for k in ("open_as", "start_lmstudio", "model") if k in saved})
    except (OSError, ValueError):
        pass
    return prefs


def lmstudio_native_url():
    return str(config().get("lmstudio_url", "http://localhost:1234/v1")).rsplit("/v1", 1)[0]


def open_app(path=""):
    launcher.open_ui(app_url(path), launch_prefs().get("open_as", "window"))


def app_url(path=""):
    c = config()
    return f"http://{c['pc_address']}:{c['port']}{path}"


def app_responds():
    """Is the app running (this one, or one started some other way)?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{config()['port']}/manifest.webmanifest", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def python_exe(windowless):
    """pythonw.exe runs without a black console window (Windows only)."""
    exe = Path(sys.executable)
    if IS_WINDOWS:
        w = exe.with_name("pythonw.exe")
        p = exe.with_name("python.exe")
        if windowless and w.exists():
            return w
        if not windowless and p.exists():
            return p
    return exe


def message_box(text, title="VersiDen"):
    """A plain Windows pop-up, for problems the user must see (pythonw has no console)."""
    if IS_WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    else:
        print(f"[{title}] {text}")


# ------------------------------------------------------------------ the app as a background process
class AppProcess:
    MAX_AUTO_RESTARTS = 3

    def __init__(self):
        self.proc, self.wanted, self.crashes, self.status = None, False, 0, "starting"
        self.lock = threading.Lock()
        self.on_change = lambda: None

    def start(self):
        with self.lock:
            LOG_DIR.mkdir(exist_ok=True)
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > 5_000_000:   # keep the log small
                LOG_FILE.replace(LOG_DIR / "app.old.log")
            log = open(LOG_FILE, "a", encoding="utf-8")
            log.write(f"\n===== started {datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
            log.flush()
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
            flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
            self.proc = subprocess.Popen([str(python_exe(windowless=False)), str(BASE / "app.py")], cwd=BASE,
                                         stdout=log, stderr=subprocess.STDOUT, env=env, creationflags=flags)
            log.close()  # the child has its own handle now
            self.wanted, self.status = True, "starting"
        self.on_change()

    def stop(self):
        with self.lock:
            self.wanted = False
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            self.status = "stopped"
        self.on_change()

    def restart(self):
        self.stop()
        time.sleep(0.5)
        self.crashes = 0
        self.start()

    def wait_ready(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            if self.proc and self.proc.poll() is not None:
                return False
            if app_responds():
                self.status = "running"
                self.on_change()
                return True
            time.sleep(0.4)
        return False

    def watch(self):
        """If the app stops by itself, start it again (up to 3 times in a row)."""
        while True:
            time.sleep(2)
            if self.wanted and self.proc and self.proc.poll() is not None:
                self.crashes += 1
                if self.crashes <= self.MAX_AUTO_RESTARTS:
                    self.status = "restarting"
                    self.on_change()
                    self.start()
                    self.wait_ready()
                else:
                    self.wanted, self.status = False, "stopped (see Show log)"
                    self.on_change()
            elif self.status == "running" and self.proc and self.proc.poll() is None:
                self.crashes = 0


# ------------------------------------------------------------------ start with Windows
def startup_command():
    return f'"{python_exe(windowless=True)}" "{BASE / "tray.pyw"}" --background'


def startup_enabled():
    if not IS_WINDOWS:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            value, _ = winreg.QueryValueEx(k, RUN_NAME)
            return bool(value)
    except OSError:
        return False


def migrate_startup():
    """Earlier versions registered "Start with Windows" under another name: move it over."""
    if not IS_WINDOWS:
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
            for old in OLD_RUN_NAMES:
                try:
                    winreg.QueryValueEx(k, old)
                except OSError:
                    continue
                winreg.DeleteValue(k, old)
                winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, startup_command())
    except OSError:
        pass


def set_startup(on):
    if not IS_WINDOWS:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except FileNotFoundError:
                pass


# ------------------------------------------------------------------ the tray icon
def run_tray(app, open_browser):
    try:
        import pystray
        from PIL import Image
    except ImportError:
        message_box("The tray icon needs two small add-ons.\n\nOpen a terminal in the app's folder and run:\n\n"
                    "    pip install pystray pillow\n\nThen double-click start.bat again.\n\n"
                    "(The app itself is running anyway; this window is just to tell you.)")
        open_browser and open_app()
        while app.wanted:          # keep the app running without the icon
            time.sleep(5)
        return

    name = config()["app_name"]
    if name in ("", "Roleplay"):
        name = "VersiDen"
    icon_img = Image.open(BASE / "static" / "icons" / "icon-192.png")

    def title():
        return f"{name}: {app.status}"

    def do_open(icon=None, item=None):
        open_app()

    def do_phone(icon=None, item=None):
        open_app("/settings")

    def do_shortcuts(icon, item):
        try:
            launcher.make_shortcuts()
            message_box("VersiDen is now on your Desktop and in the Start menu.\n\n"
                        "Tip: right-click it in the Start menu and choose \"Pin to taskbar\" or \"Pin to Start\".")
        except OSError as e:
            message_box(f"Couldn't add the shortcuts: {e}")

    def do_restart(icon, item):
        threading.Thread(target=lambda: (app.restart(), app.wait_ready()), daemon=True).start()

    def do_log(icon, item):
        LOG_DIR.mkdir(exist_ok=True)
        LOG_FILE.touch()
        os.startfile(LOG_FILE) if IS_WINDOWS else print(LOG_FILE)

    def do_startup(icon, item):
        try:
            set_startup(not startup_enabled())
        except OSError as e:
            message_box(f"Couldn't change \"Start with Windows\": {e}")
        icon.update_menu()

    def do_quit(icon, item):
        app.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(f"Open {name}", do_open, default=True),   # default = left-click / double-click
        pystray.MenuItem("Phone access…", do_phone),
        pystray.MenuItem("Restart", do_restart),
        pystray.MenuItem("Show log", do_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Add to Desktop and Start menu", do_shortcuts),
        pystray.MenuItem("Start with Windows", do_startup, checked=lambda item: startup_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", do_quit),
    )
    icon = pystray.Icon("versiden", icon_img, title(), menu)

    def refresh():
        icon.title = title()
    app.on_change = refresh

    def when_ready():
        if app.wait_ready() and open_browser:
            open_app()
        elif app.status != "running":
            app.status = "didn't start (see Show log)"
            refresh()
    threading.Thread(target=when_ready, daemon=True).start()
    icon.run()


def main():
    background = "--background" in sys.argv       # started with Windows: don't pop the browser open
    migrate_startup()
    if app_responds():                            # already running: just open it
        if not background:
            open_app()
        return
    prefs = launch_prefs()
    if prefs.get("start_lmstudio"):               # start LM Studio's server alongside (in the background)
        launcher.start_lmstudio_in_background(lmstudio_native_url(), prefs.get("model", ""), LOG_DIR / "lmstudio.log")
    app = AppProcess()
    app.start()
    threading.Thread(target=app.watch, daemon=True).start()
    try:
        run_tray(app, open_browser=not background)
    finally:
        if app.wanted:
            app.stop()


def selftest():
    """For development: start, restart, crash-recover and stop the app without a tray icon."""
    app = AppProcess()
    t = time.time(); app.start(); ok = app.wait_ready()
    print(f"started: {ok} in {time.time() - t:.1f}s, responds: {app_responds()}")
    threading.Thread(target=app.watch, daemon=True).start()
    pid = app.proc.pid; app.restart(); ok = app.wait_ready()
    print(f"restart: {ok}, new process: {app.proc.pid != pid}")
    app.proc.kill(); time.sleep(0.3); print(f"after crash, responds: {app_responds()}")
    time.sleep(3.5); ok = app.wait_ready()
    print(f"auto-restarted after crash: {ok}, status: {app.status}")
    app.stop(); time.sleep(1); print(f"after quit, responds: {app_responds()}")
    print(f"startup command would be: {startup_command()}")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        sys.exit(0)
    try:
        main()
    except Exception:  # pythonw has no console: write the problem down and show it
        LOG_DIR.mkdir(exist_ok=True)
        TRAY_LOG.write_text(traceback.format_exc(), encoding="utf-8")
        message_box(f"The tray icon ran into a problem. Details are in:\n{TRAY_LOG}")
