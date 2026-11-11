"""
Launcher helpers shared by the tray icon (tray.pyw) and the Settings page (app.py):

- open VersiDen in its own app window (Edge or Chrome "app mode") or in a normal browser tab
- add VersiDen shortcuts, with its icon, to the Desktop and the Start menu
- optionally start LM Studio's server (and load your model) when VersiDen starts

Standard library only, so the tray can import it without loading the whole app.
Everything here is Windows-specific; on other systems it falls back to doing nothing
(or opening a normal browser tab).
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
IS_WINDOWS = os.name == "nt"
ICON = BASE / "static" / "icons" / "versiden.ico"
SHORTCUT_NAME = "VersiDen.lnk"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0

# Launcher choices live with the model settings (worlds/.settings.json), so they survive updates.
LAUNCH_DEFAULTS = {"open_as": "window", "start_lmstudio": False}


def _env(name, default=""):
    return os.environ.get(name, default)


# ------------------------------------------------------------------ app window or tab
def browser_for_app_window():
    """Edge comes with Windows; Chrome is the fallback. None if neither is found."""
    if not IS_WINDOWS:
        return None
    roots = [_env("ProgramFiles(x86)"), _env("ProgramFiles"), _env("LOCALAPPDATA")]
    candidates = [Path(r) / "Microsoft" / "Edge" / "Application" / "msedge.exe" for r in roots if r]
    candidates += [Path(r) / "Google" / "Chrome" / "Application" / "chrome.exe" for r in roots if r]
    for p in candidates:
        if p.exists():
            return p
    found = shutil.which("msedge") or shutil.which("chrome")
    return Path(found) if found else None


def open_ui(url, open_as="window"):
    """Open VersiDen: in its own window (no address bar or tabs) when possible, otherwise a tab."""
    if open_as == "window":
        exe = browser_for_app_window()
        if exe:
            try:
                subprocess.Popen([str(exe), f"--app={url}"], creationflags=NO_WINDOW)
                return "window"
            except OSError:
                pass
    webbrowser.open(url)
    return "tab"


# ------------------------------------------------------------------ Desktop and Start menu shortcuts
def pythonw():
    """The windowless Python, so the shortcut starts VersiDen without a black console window."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return w if w.exists() else exe


def _special_folders():
    """Desktop (OneDrive-aware) and the Start menu's Programs folder, as Windows reports them."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         "[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('Programs')"],
        capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    if len(lines) < 2:
        raise OSError(out.stderr.strip() or "Windows didn't say where the Desktop is.")
    return Path(lines[0]), Path(lines[1])


def shortcut_paths():
    if not IS_WINDOWS:
        return []
    try:
        desktop, programs = _special_folders()
    except (OSError, subprocess.SubprocessError):
        return []
    return [desktop / SHORTCUT_NAME, programs / SHORTCUT_NAME]


def shortcuts_exist():
    paths = shortcut_paths()
    return bool(paths) and all(p.exists() for p in paths)


def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def shortcut_script(paths, target, args, workdir, icon):
    """PowerShell that writes .lnk files through Windows' own shortcut maker (no add-ons needed)."""
    lines = ["$s = New-Object -ComObject WScript.Shell"]
    for p in paths:
        lines += [f"$l = $s.CreateShortcut({_ps_quote(p)})",
                  f"$l.TargetPath = {_ps_quote(target)}",
                  f"$l.Arguments = {_ps_quote(args)}",
                  f"$l.WorkingDirectory = {_ps_quote(workdir)}",
                  f"$l.IconLocation = {_ps_quote(str(icon) + ',0')}",
                  "$l.Description = 'Start VersiDen'",
                  "$l.Save()"]
    return "; ".join(lines)


def make_shortcuts():
    """Add (or refresh) VersiDen on the Desktop and in the Start menu. Returns the paths written."""
    if not IS_WINDOWS:
        raise OSError("Shortcuts can only be added on Windows.")
    paths = shortcut_paths()
    if not paths:
        raise OSError("Couldn't find your Desktop or Start menu folder.")
    script = shortcut_script(paths, pythonw(), f'"{BASE / "tray.pyw"}"', BASE, ICON)
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
    if out.returncode != 0 or not all(p.exists() for p in paths):
        raise OSError(out.stderr.strip() or "Windows didn't create the shortcuts.")
    return paths


# ------------------------------------------------------------------ LM Studio
def lms_exe():
    """LM Studio's command-line helper, if it's set up."""
    found = shutil.which("lms")
    if found:
        return Path(found)
    home = Path(_env("USERPROFILE") or Path.home())
    for name in ("lms.exe", "lms"):
        p = home / ".lmstudio" / "bin" / name
        if p.exists():
            return p
    return None


def lmstudio_responds(native_url):
    try:
        with urllib.request.urlopen(f"{native_url}/v1/models", timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


def model_loaded(native_url, model):
    """Is this model already loaded? (None if LM Studio can't say.)"""
    try:
        with urllib.request.urlopen(f"{native_url}/api/v0/models", timeout=3) as r:
            data = json.load(r).get("data", [])
    except (OSError, ValueError):
        return None
    return any(m.get("id") == model and m.get("state") == "loaded" for m in data)


def start_lmstudio(native_url, model="", log_path=None, wait=60):
    """Start LM Studio's server (headless, no window) and load `model` if it isn't loaded yet.
    Returns a short plain-words result. Safe to call when LM Studio is already running."""
    def log(msg):
        if log_path:
            Path(log_path).parent.mkdir(exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")

    lms = lms_exe()
    if not lms:
        log("lms not found: LM Studio's command-line helper isn't set up.")
        return "LM Studio's command-line helper isn't set up, so VersiDen can't start LM Studio for you."
    port = native_url.rsplit(":", 1)[-1].split("/")[0] if native_url.count(":") >= 2 else "1234"

    def run(*args, timeout=120):
        try:
            out = subprocess.run([str(lms), *args], capture_output=True, text=True, timeout=timeout,
                                 creationflags=NO_WINDOW)
            log(f"lms {' '.join(args)} -> {out.returncode} {(out.stdout + out.stderr).strip()[-300:]}")
            return out.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            log(f"lms {' '.join(args)} failed: {e}")
            return False

    if not lmstudio_responds(native_url):
        run("daemon", "up", timeout=60)          # newer LM Studio: the headless service (harmless if missing)
        run("server", "start", "--port", port, timeout=60)
        end = time.time() + wait
        while time.time() < end and not lmstudio_responds(native_url):
            time.sleep(1)
        if not lmstudio_responds(native_url):
            return "Tried to start LM Studio's server, but it didn't answer. Open LM Studio to check."
    if model and model_loaded(native_url, model) is False:
        ok = run("load", model, "--yes", timeout=600)
        return f"LM Studio is running; {'loaded ' + model if ok else 'couldn' + chr(39) + 't load ' + model}."
    return "LM Studio is running."


def start_lmstudio_in_background(native_url, model="", log_path=None, on_done=None):
    def go():
        msg = start_lmstudio(native_url, model, log_path)
        if on_done:
            on_done(msg)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    return t
