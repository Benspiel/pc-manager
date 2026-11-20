"""PC-Manager Setup: laedt das Projekt von GitHub, legt es in einen festen Ordner,
installiert die Abhaengigkeiten, richtet den Autostart ein und startet das
Programm. Danach aktualisiert sich das Programm selbst von GitHub (launcher.py).
Nur Python noetig, sonst nichts (nur Standardbibliothek).

Aufruf (Doppelklick oder):
    python setup.py

Optionen:
    --dir ORDNER      Zielordner (Standard: C:\\ProgramData\\PC-Manager)
    --pc-id NAME      pc_id fuer diesen Rechner (Standard: leer = Hostname)
    --no-autostart    keinen Autostart einrichten (dann auch kein Admin noetig)
    --no-start        Programm nach der Installation nicht starten

Lehrer-PC (Webserver fuer das Panel statt Schueler-Programm):
    python setup.py --panel [--port 8080] [--network]
    Laedt die Dateien nach %LOCALAPPDATA%\\PC-Manager-Panel, startet den
    Panel-Webserver ohne Fenster und richtet dafuer einen Autostart ein
    (Verknuepfung im Autostart-Ordner, kein Admin noetig). Das Panel ist dann
    unter http://localhost:8080/teacher-panel.html erreichbar. --network macht
    es auch im Netz erreichbar (0.0.0.0).

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


def urlopen_compat(req, timeout=20):
    """Wie urllib.request.urlopen. Schlaegt die Zertifikatspruefung von Python fehl
    (z. B. fehlendes Stammzertifikat im Windows-Speicher oder TLS-Proxy), wird der
    Aufruf mit curl.exe wiederholt, das den Windows-Zertifikatsspeicher nutzt
    (Schannel, laedt fehlende Stammzertifikate nach). Die Zertifikatspruefung
    bleibt dabei AKTIV, sie wird nicht abgeschaltet."""
    import io
    import ssl
    if isinstance(req, str):
        req = urllib.request.Request(req)
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        # Zertifikatsfehler ODER "Verbindung verweigert" (WinError 10061, z. B. ein
        # lokaler Proxy aus den Windows-Einstellungen, den urllib nutzt, curl.exe aber nicht)
        if not isinstance(getattr(e, "reason", None), (ssl.SSLError, ConnectionRefusedError)):
            raise
        ssl_error = e
    for extra in ([], ["--ssl-no-revoke"]):  # 2. Versuch: ohne Sperrlistenpruefung (Proxys blocken die oft)
        cmd = ["curl.exe", "-sS", "-L", "--max-time", str(int(timeout)), *extra,
               "-X", req.get_method(), "-w", "\n%{http_code}"]
        for key, value in req.header_items():
            cmd += ["-H", f"{key}: {value}"]
        if req.data is not None:
            cmd += ["--data-binary", "@-"]
        cmd.append(req.full_url)
        try:
            r = subprocess.run(cmd, input=req.data, capture_output=True, creationflags=0x08000000)
        except OSError:
            raise ssl_error from None  # curl.exe nicht vorhanden
        if r.returncode == 0:
            body, _, code = r.stdout.rpartition(b"\n")
            code = int(code or 0)
            if code >= 400:
                raise urllib.error.HTTPError(req.full_url, code, "HTTP-Fehler", {}, io.BytesIO(body))
            return io.BytesIO(body)
    raise ssl_error


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


def stop_running_instances(names=("pc_manager", "launcher")):
    """Beendet einen bereits laufenden Starter/pc_manager.py (bzw. den Panel-Server),
    damit nach einem Update nicht zwei Instanzen laufen."""
    pattern = "(" + "|".join(names) + ")\\.(py|pyw)"
    ps = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -match '{pattern}' -and $_.ProcessId -ne $PID }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)


def download_and_copy(target):
    print(f"Lade {REPO_ZIP} ...")
    try:
        with urlopen_compat(REPO_ZIP, timeout=60) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        sys.exit(
            f"Download fehlgeschlagen: {e}\n"
            "Pruefen: 'curl.exe -I https://github.com' in der Eingabeaufforderung. Kommt dort "
            "ebenfalls ein Zertifikatsfehler, fehlt dem PC ein Stammzertifikat (Windows-Updates "
            "installieren) oder das Netzwerk filtert HTTPS (IT fragen, github.com freigeben)."
        )
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
    subprocess.Popen([pythonw(), str(target / "launcher.py")], cwd=target, creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("PC-Manager gestartet (Tray-Icon unten rechts).")


PANEL_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PC-Manager-Panel"
PANEL_LINK = (Path(os.environ.get("APPDATA", str(Path.home())))
              / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "PC-Manager-Panel.lnk")


def create_panel_shortcut(target, port, bind):
    """Verknuepfung im Autostart-Ordner (startet den Panel-Server ohne Fenster)."""
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:PCM_LNK);"
        "$s.TargetPath=$env:PCM_EXE;$s.Arguments=$env:PCM_ARGS;"
        "$s.WorkingDirectory=$env:PCM_DIR;$s.WindowStyle=7;$s.Save()"
    )
    env = dict(os.environ,
               PCM_LNK=str(PANEL_LINK), PCM_EXE=pythonw(), PCM_DIR=str(target),
               PCM_ARGS=subprocess.list2cmdline([str(target / "serve_panel.pyw"), str(port), bind]))
    PANEL_LINK.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("Autostart-Verknuepfung konnte nicht angelegt werden:\n" + (result.stderr or "").strip())
    else:
        print(f"Autostart eingerichtet: {PANEL_LINK}")


def setup_panel(args):
    target = Path(args.dir).expanduser().resolve() if args.dir else PANEL_DIR
    bind = "0.0.0.0" if args.network else "127.0.0.1"
    stop_running_instances(("serve_panel",))
    download_and_copy(target)
    if not args.no_autostart:
        create_panel_shortcut(target, args.port, bind)
    if not args.no_start:
        flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
        subprocess.Popen([pythonw(), str(target / "serve_panel.pyw"), str(args.port), bind],
                         cwd=target, creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"Panel-Server gestartet: http://localhost:{args.port}/teacher-panel.html")
    if args.network:
        print(f"Im Netz: Port {args.port} in der Windows-Firewall erlauben und in Appwrite "
              "unter Plattformen den Hostnamen/die IP dieses PCs eintragen.")
    else:
        print("Appwrite: unter Plattformen muss 'localhost' als Web-Plattform eingetragen sein.")
    print("\nFertig.")


def main():
    if sys.platform != "win32":
        sys.exit("Dieses Setup funktioniert nur unter Windows.")
    ap = argparse.ArgumentParser(description="PC-Manager Setup")
    ap.add_argument("--dir", default=None)
    ap.add_argument("--panel", action="store_true", help="Panel-Webserver statt Schueler-Programm")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--network", action="store_true", help="Panel im Netz erreichbar (0.0.0.0)")
    ap.add_argument("--pc-id", default="")
    ap.add_argument("--no-autostart", action="store_true")
    ap.add_argument("--no-start", action="store_true")
    ap.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.panel:
        setup_panel(args)
        return
    target = Path(args.dir or DEFAULT_DIR).expanduser().resolve()

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
