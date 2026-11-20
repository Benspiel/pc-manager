"""Starter mit Auto-Update fuer PC-Manager.

Der Autostart startet dieses Skript (nicht pc_manager.py direkt). Es
  1. holt beim Start die neueste Version von GitHub (oeffentliches Repo,
     kein API-Key noetig), wenn es dort einen neueren Commit gibt,
  2. startet pc_manager.py,
  3. prueft danach regelmaessig, ob es einen neuen Commit gibt, und startet bei
     einem Update pc_manager.py automatisch mit der neuen Version neu.

Beendet sich pc_manager.py von selbst (z. B. Rechtsklick auf das Tray-Icon >
Beenden, oder Absturz), beendet sich auch dieser Starter - kein automatischer
Neustart. Beim naechsten Anmelden wird zuerst wieder aktualisiert, ein
fehlerhafter Stand heilt sich also mit dem naechsten Commit selbst.

Einstellungen in config.json (alle optional):
    "auto_update": true            false = nie aktualisieren
    "update_check_minutes": 30     Pruefintervall

Nur Standardbibliothek. Wird mit pythonw.exe gestartet (kein Fenster).
"""
import io
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = "Benspiel/pc-manager"
BRANCH = "main"
BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"
VERSION_FILE = BASE / ".version"
LOG_FILE = BASE / "launcher.log"
# Diese Dateien werden beim Update nie ueberschrieben.
PROTECTED = {"config.json", ".version", "launcher.log"}
USER_AGENT = "git/2.45.0"  # das Git-Protokoll-Endpoint erwartet einen git-User-Agent


def log(msg):
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 100_000:
            LOG_FILE.write_text("", encoding="utf-8")
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def local_version():
    try:
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def remote_version():
    """Commit-SHA des Branches auf GitHub (wie 'git ls-remote'), None bei Fehler."""
    url = f"https://github.com/{REPO}.git/info/refs?service=git-upload-pack"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read().decode("latin-1")
    except Exception as e:
        log(f"Versionsabfrage fehlgeschlagen: {e}")
        return None
    m = re.search(r"([0-9a-f]{40}) refs/heads/" + re.escape(BRANCH) + r"\b", data)
    return m.group(1) if m else None


def download_version(sha):
    """Laedt genau diesen Commit, prueft ihn und kopiert die Dateien ins BASE.
    True bei Erfolg. Bei jedem Fehler bleibt die alte Version unveraendert."""
    url = f"https://codeload.github.com/{REPO}/zip/{sha}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(tmp)
            roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
            if len(roots) != 1:
                raise RuntimeError("unerwartete ZIP-Struktur")
            src = roots[0]
            # Nicht uebernehmen, wenn die Hauptdateien nicht kompilieren.
            for name in ("pc_manager.py", "launcher.py"):
                if (src / name).exists():
                    py_compile.compile(str(src / name), cfile=os.path.join(tmp, name + "c"), doraise=True)
            if not (src / "pc_manager.py").exists():
                raise RuntimeError("pc_manager.py fehlt im Download")
            for item in src.rglob("*"):
                rel = item.relative_to(src)
                if item.is_dir() or "__pycache__" in rel.parts or rel.as_posix() in PROTECTED:
                    continue
                dest = BASE / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                part = dest.with_name(dest.name + ".new")
                shutil.copy2(item, part)
                os.replace(part, dest)
        VERSION_FILE.write_text(sha, encoding="utf-8")
        log(f"Aktualisiert auf {sha[:7]}")
        return True
    except Exception as e:
        log(f"Update fehlgeschlagen: {e}")
        return False


def update_if_needed():
    """True, wenn eine neue Version installiert wurde."""
    cfg = load_config()
    if cfg.get("auto_update", True) is False:
        return False
    remote = remote_version()
    if not remote or remote == local_version():
        return False
    return download_version(remote)


def start_child():
    return subprocess.Popen(
        [sys.executable, str(BASE / "pc_manager.py")], cwd=str(BASE),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def stop_child(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def main():
    update_if_needed()
    while True:
        proc = start_child()
        log(f"pc_manager gestartet (Version {local_version()[:7] or 'unbekannt'})")
        while True:
            cfg = load_config()
            minutes = max(1, int(cfg.get("update_check_minutes", 30) or 30))
            try:
                code = proc.wait(timeout=minutes * 60)
                log(f"pc_manager beendet (Code {code}) - Starter beendet sich ebenfalls")
                return
            except subprocess.TimeoutExpired:
                pass
            if cfg.get("auto_update", True) is False:
                continue
            remote = remote_version()
            if remote and remote != local_version() and download_version(remote):
                stop_child(proc)
                break  # aeussere Schleife startet pc_manager mit der neuen Version


if __name__ == "__main__":
    main()
