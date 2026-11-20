"""PC-Manager Setup: laedt das Projekt von GitHub, legt es in einen festen Ordner,
installiert die Abhaengigkeiten, richtet den Autostart ein und startet das
Programm. Nur Python noetig, sonst nichts (nur Standardbibliothek).

Aufruf (Doppelklick oder):
    python setup.py

Optionen:
    --dir ORDNER      Zielordner (Standard: C:\\ProgramData\\PC-Manager)
    --pc-id NAME      pc_id fuer diesen Rechner (Standard: leer = Hostname)
    --no-autostart    keinen Autostart einrichten (dann auch kein Admin noetig)
    --no-start        Programm nach der Installation nicht starten

Der Autostart ist eine geplante Aufgabe mit erhoehten Rechten und braucht
Administratorrechte. Das Skript fragt dafuer selbst per UAC nach.
Erneutes Ausfuehren aktualisiert die Dateien; eine vorhandene config.json
bleibt dabei unveraendert.
"""
import argparse
import ctypes
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_ZIP = "https://github.com/Benspiel/pc-manager/archive/refs/heads/main.zip"
DEFAULT_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "PC-Manager"
REQUIREMENTS = ["pystray", "pillow"]


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    """Startet dieses Skript mit UAC-Abfrage erneut und beendet die aktuelle Instanz."""
    script = str(Path(__file__).resolve())
    params = subprocess.list2cmdline([script, *sys.argv[1:], "--elevated"])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    if rc <= 32:
        sys.exit("Administratorrechte wurden nicht erteilt. Abbruch "
                 "(oder mit --no-autostart ohne Autostart installieren).")
    sys.exit(0)


def stop_running_instances():
    """Beendet eine bereits laufende pc_manager.py, damit nach einem Update nicht
    zwei Instanzen laufen."""
    ps = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -match 'pc_manager\\.py' -and $_.ProcessId -ne $PID } | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def download_and_copy(target):
    print(f"Lade {REPO_ZIP} ...")
    with urllib.request.urlopen(REPO_ZIP, timeout=60) as resp:
        data = resp.read()
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if len(roots) != 1:
            sys.exit("Unerwartete ZIP-Struktur.")
        src = roots[0]
        keep_config = (target / "config.json").exists()
        for item in src.rglob("*"):
            rel = item.relative_to(src)
            if rel.parts[0] == "__pycache__" or "__pycache__" in rel.parts:
                continue
            if keep_config and rel.as_posix() == "config.json":
                continue
            dest = target / rel
            if item.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
    print(f"Dateien liegen in {target}")
    return keep_config


def prepare_config(target, keep_config, pc_id):
    cfg_file = target / "config.json"
    if keep_config:
        print("Vorhandene config.json bleibt unveraendert.")
        return
    cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    cfg["pc_id"] = pc_id  # leer = Hostname dieses Rechners
    cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    shown = pc_id or f"(Hostname: {os.environ.get('COMPUTERNAME', '?')})"
    print(f"config.json angelegt, pc_id = {shown}")


def install_requirements():
    print("Installiere Abhaengigkeiten:", ", ".join(REQUIREMENTS))
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *REQUIREMENTS]
    )
    if result.returncode != 0:
        sys.exit("pip install ist fehlgeschlagen (Internetverbindung / Python-Installation pruefen).")


def pythonw():
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate if candidate.exists() else sys.executable)


def setup_autostart(target):
    result = subprocess.run(
        [sys.executable, str(target / "pc_manager.py"), "--install-autostart"],
        cwd=target, capture_output=True, text=True,
    )
    print((result.stdout or "").strip())
    if result.returncode != 0:
        print("Autostart konnte nicht eingerichtet werden:\n" + (result.stderr or "").strip())


def start_program(target):
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    subprocess.Popen([pythonw(), str(target / "pc_manager.py")], cwd=target, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("PC-Manager gestartet (Tray-Icon unten rechts).")


def main():
    if sys.platform != "win32":
        sys.exit("Dieses Setup funktioniert nur unter Windows.")
    ap = argparse.ArgumentParser(description="PC-Manager Setup")
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--pc-id", default="")
    ap.add_argument("--no-autostart", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    ap.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    target = Path(args.dir).expanduser().resolve()

    if not args.no_autostart and not is_admin():
        print("Fuer den Autostart sind Administratorrechte noetig - UAC-Abfrage folgt ...")
        relaunch_as_admin()

    try:
        stop_running_instances()
        keep_config = download_and_copy(target)
        prepare_config(target, keep_config, args.pc_id)
        install_requirements()
        if not args.no_autostart:
            setup_autostart(target)
        if not args.no_start:
            start_program(target)
        print("\nFertig.")
    finally:
        if args.elevated:
            input("\nEnter druecken zum Schliessen ...")


if __name__ == "__main__":
    main()
