"""PC-Manager: holt einen Status aus Appwrite und sperrt bei bestimmtem Wert den PC.

mode "windows" (Standard): echte Windows-Sperre (wie Win+L), Entsperren per PIN/Passwort.
mode "overlay": Vollbild-Fenster mit Sperrbild (keine echte Sperre).

Laeuft als normales Tray-Programm: Icon unten rechts im Infobereich, Rechtsklick
zeigt den Verbindungsstatus, "Beenden" beendet das Programm wirklich (kein
automatischer Neustart, kein Verstecken vor dem Task-Manager).

Start:              python pc_manager.py          (oder pythonw.exe fuer kein Konsolenfenster)
Demo/Test:           python pc_manager.py --demo
Autostart einrichten: python pc_manager.py --install-autostart  (ALS ADMINISTRATOR ausfuehren!)
Autostart entfernen:  python pc_manager.py --uninstall-autostart

Abhaengigkeiten: pystray, Pillow (pip install pystray pillow). Sonst nur stdlib.
"""
import ctypes
import json
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import winreg
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw
import pystray

BASE = Path(__file__).resolve().parent
CONFIG_FILE = BASE / "config.json"
SCRIPT_FILE = Path(__file__).resolve()
AUTOSTART_TASK_NAME = "PC-Manager"


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def resolve_pc_id(cfg):
    """Welche Zeile (Row/Dokument) in Appwrite gehoert zu diesem PC.

    Reihenfolge: explizites 'document_id' in der Config (Altlast/Override) >
    explizites 'pc_id' > Hostname dieses Rechners. So muss pro PC nur die
    Config kopiert werden, ohne jedes Mal die ID anzupassen - solange IT den
    Hostnamen beim Anlegen der Appwrite-Zeile verwendet hat.
    """
    return cfg.get("document_id") or cfg.get("pc_id") or socket.gethostname()


def fetch_document(cfg):
    """Liest die komplette, zu diesem PC gehoerende Appwrite-Zeile (Status,
    aktueller Befehl, ...)."""
    pc_id = resolve_pc_id(cfg)
    url = (
        f"{cfg['endpoint'].rstrip('/')}/databases/{cfg['database_id']}"
        f"/collections/{cfg['collection_id']}/documents/{pc_id}"
    )
    headers = {
        "X-Appwrite-Project": cfg["project_id"],
        "Accept": "application/json",
        "User-Agent": "pc-manager/1.0",  # Standard-UA von Python wird teils vom Server geblockt (403)
    }
    if cfg.get("api_key"):
        headers["X-Appwrite-Key"] = cfg["api_key"]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # Noch keine Zeile fuer diesen PC: einmalig selbst anlegen lassen
            # (ueber die heartbeat-Function) und direkt noch einmal lesen.
            if try_register(cfg, pc_id):
                return fetch_document(cfg)
            raise urllib.error.URLError(
                f"Keine Appwrite-Zeile fuer PC-ID '{pc_id}' (404), Selbstregistrierung nicht moeglich"
            ) from e
        raise


REGISTER_RETRY_SECONDS = 300
_last_register_try = 0.0


def try_register(cfg, pc_id):
    """Laesst die heartbeat-Function die Zeile fuer diesen PC anlegen (status
    'unlocked'). Hoechstens alle 5 Minuten, damit ein dauerhaft scheiternder
    Versuch (z. B. Obergrenze erreicht) nicht alle paar Sekunden die Function
    aufruft. Abschaltbar mit "auto_register": false. True = Zeile existiert jetzt."""
    global _last_register_try
    if cfg.get("auto_register", True) is False:
        return False
    now = time.monotonic()
    if _last_register_try and now - _last_register_try < REGISTER_RETRY_SECONDS:
        return False
    _last_register_try = now
    ok = report(cfg, pc_id, register=True, pc_name=socket.gethostname())
    if ok:
        _last_register_try = 0.0
    return ok


def report(cfg, pc_id, **fields):
    """Meldet der 'heartbeat'-Appwrite-Function, dass dieser PC gerade laeuft
    (last_seen), und optional zusaetzlich 'programs'/'search_results'/
    'command_result'/'ack_command_id' - das sind die einzigen Felder, die diese
    Function akzeptiert (siehe functions/heartbeat/src/main.py). 'ack_command_id'
    raeumt das 'command'-Feld NUR, wenn dort noch genau dieser Befehl steht (sonst
    koennte ein inzwischen neu eingetroffener Befehl verschluckt werden). Rein
    informativ: Fehler hier duerfen die Sperrfunktion nicht beeinflussen, daher
    werden sie verschluckt statt weitergereicht."""
    url = f"{cfg['endpoint'].rstrip('/')}/functions/heartbeat/executions"
    body = {"pc_id": pc_id, **fields}
    payload = json.dumps({"body": json.dumps(body), "async": False}).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Appwrite-Project": cfg["project_id"],
        "User-Agent": "pc-manager/1.0",
    }
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.load(resp)
        # Die Function-Antwort steckt im Feld "responseBody" der Execution.
        reply = json.loads(result.get("responseBody") or "{}")
        return reply.get("ok") is True
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Programme auflisten/deinstallieren (fuer die Lehrer-Panel-Funktion
# "Programme verwalten")
# ---------------------------------------------------------------------------

UNINSTALL_REGISTRY_PATHS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
]


def list_installed_programs():
    """Liest die sichtbaren, deinstallierbaren Programme aus der Windows-Registry
    (dieselbe Quelle wie "Apps & Features"). Gibt pro Programm eine stabile 'id'
    (fuer spaetere Deinstall-Befehle) plus Name/Version zurueck."""
    programs = {}
    for hive, path in UNINSTALL_REGISTRY_PATHS:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            for i in range(winreg.QueryInfoKey(key)[0]):
                try:
                    subkey_name = winreg.EnumKey(key, i)
                except OSError:
                    continue
                try:
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                        uninstall_string = winreg.QueryValueEx(subkey, "UninstallString")[0]
                        try:
                            system_component = winreg.QueryValueEx(subkey, "SystemComponent")[0]
                        except OSError:
                            system_component = 0
                        try:
                            version = winreg.QueryValueEx(subkey, "DisplayVersion")[0]
                        except OSError:
                            version = ""
                except OSError:
                    continue  # kein DisplayName/UninstallString -> keine normale, sichtbare Software
                if system_component:
                    continue  # z.B. Windows-Updates/Runtime-Komponenten, nicht einzeln deinstallierbar gedacht
                program_id = f"{hive}:{path}:{subkey_name}"
                programs[program_id] = {
                    "id": program_id,
                    "name": name,
                    "version": version,
                    "uninstall_string": uninstall_string,
                }
    return programs


def search_winget_packages(query):
    """Sucht im offiziellen winget-Katalog nach Paketen. winget hat (in der hier
    unterstuetzten Version) keine stabile JSON-Ausgabe - die Texttabelle wird
    deshalb ueber Spalten getrennt durch >=2 Leerzeichen geparst (gaengiger Ansatz
    fuer winget-Output, da Programmnamen kaum doppelte Leerzeichen enthalten)."""
    try:
        result = subprocess.run(
            ["winget", "search", query, "--accept-source-agreements"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    lines = result.stdout.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Name") and "Id" in line:
            start = i + 2  # Kopfzeile + "----"-Trennzeile ueberspringen
            break
    if start is None:
        return []

    packages = []
    for line in lines[start:]:
        if not line.strip():
            continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 2:
            continue
        packages.append({"id": parts[1], "name": parts[0]})
    return packages[:20]


# ---------------------------------------------------------------------------
# Installations-Richtlinie (darf der angemeldete Nutzer selbst Software
# installieren?) - vom Lehrer ueber das Panel umschaltbar.
# ---------------------------------------------------------------------------

INSTALLER_POLICY_PATH = r"SOFTWARE\Policies\Microsoft\Windows\Installer"


def set_install_policy(allow):
    """Erlaubt/verbietet dem AKTUELL ANGEMELDETEN Nutzer, Software ueber den
    Windows Installer (MSI) zu installieren - das ist die offizielle, von
    Microsoft dokumentierte Gruppenrichtlinie dafuer, nur in der Variante fuer
    den eigenen Nutzer (HKCU), nicht fuer die ganze Maschine (HKLM). Deshalb
    klappt das ohne Admin-Rechte. Deckt die meisten alltaeglichen Installationen
    ab, aber NICHT jeden EXE-basierten Installer (dafuer braeuchte es
    AppLocker/Software Restriction Policies - deutlich aufwaendiger)."""
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, INSTALLER_POLICY_PATH)
        with key:
            if allow:
                try:
                    winreg.DeleteValue(key, "DisableMSI")
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, "DisableMSI", 0, winreg.REG_DWORD, 2)  # 2 = alle MSI-Installationen verbieten
    except OSError as e:
        print(f"Installations-Richtlinie konnte nicht gesetzt werden: {e}")


# ---------------------------------------------------------------------------
# Tray-Icon
# ---------------------------------------------------------------------------

def make_icon_image(color):
    """Einfacher farbiger Kreis als Tray-Icon (gruen=verbunden, rot=Fehler, grau=startet)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=color, outline=(30, 30, 30, 255), width=3)
    return img


ICON_OK = make_icon_image((40, 170, 80, 255))
ICON_ERR = make_icon_image((200, 50, 50, 255))
ICON_INIT = make_icon_image((140, 140, 140, 255))


def enable_per_monitor_dpi_awareness():
    """Ohne das berechnet Windows bei Monitoren mit unterschiedlicher Skalierung
    (z.B. 100% + 125%) Fenstergroessen/-positionen falsch - sichtbar als z.B. nur
    halb schwarzer Sperrbildschirm. Muss vor dem ersten Tk-Fenster passieren."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_monitor_rects():
    """Liefert (links, oben, breite, hoehe) fuer jeden tatsaechlich angeschlossenen Monitor."""
    rects = []
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(wintypes.RECT), ctypes.c_double
    )

    def callback(_hmonitor, _hdc, lprect, _data):
        r = lprect.contents
        rects.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    ctypes.windll.user32.EnumDisplayMonitors(0, 0, MonitorEnumProc(callback), 0)
    return rects


class LockApp:
    def __init__(self, cfg, demo=False):
        self.cfg = cfg
        self.demo = demo
        self.locked = False
        self.exit_requested = False
        self.last_error = None
        self.results = queue.Queue()
        self.extra_windows = []
        self.known_programs = {}
        self.last_command_id = None
        self.last_install_allowed = None  # None = noch nie durchgesetzt -> beim ersten Poll immer setzen

        self.root = tk.Tk()
        self.root.title("PC-Manager-Sperrbildschirm")
        self.root.withdraw()
        self.root.configure(bg="black", cursor="none")
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)  # Alt+F4 ignorieren (Beenden laeuft ueber das Tray-Icon)
        self.root.bind("<Escape>", self.on_escape)
        # overrideredirect VOR dem ersten Anzeigen setzen (nicht erst beim Sperren):
        # nachtraeglich auf ein bereits "realisiertes" Fenster umschalten greift unter
        # Windows manchmal nur halb (Rahmen-Reste in einer Ecke, siehe span_all_monitors).
        self.root.overrideredirect(True)

        self.build_screen()
        self.icon = self.build_tray_icon()
        self.icon_thread = threading.Thread(target=self.icon.run, daemon=True)
        self.icon_thread.start()

        self.root.after(200, self.poll_results)
        if demo:
            self.set_locked(True)
        else:
            self.start_fetch()

    # ---------- Tray ----------
    def build_tray_icon(self):
        menu = pystray.Menu(
            pystray.MenuItem(self.tray_status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden", self.on_tray_exit),
        )
        return pystray.Icon("pc-manager", ICON_INIT, "PC-Manager", menu)

    def tray_status_text(self, _item=None):
        if self.demo:
            return "Demo-Modus"
        if self.last_error:
            return f"Fehler: {self.last_error[:40]}"
        state = "gesperrt" if self.locked else "entsperrt"
        return f"Verbunden - PC ist {state}"

    def refresh_tray(self):
        self.icon.icon = ICON_ERR if self.last_error else ICON_OK
        self.icon.title = "PC-Manager - " + self.tray_status_text()
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def on_tray_exit(self, _icon, _item):
        self.exit_requested = True

    # ---------- UI ----------
    def build_screen(self):
        self.image = None
        img_path = BASE / self.cfg.get("lock_image", "lock.png")
        if img_path.exists():
            try:
                self.image = tk.PhotoImage(file=str(img_path))  # PNG/GIF
            except tk.TclError:
                self.image = None
        self.add_lock_label(self.root)

    def add_lock_label(self, parent):
        """Baut das Sperr-Layout (Bild oder Text) in `parent`. Das PhotoImage
        (self.image) kann von mehreren Labels/Fenstern gleichzeitig genutzt
        werden, da alle Toplevels denselben Tk-Interpreter wie self.root teilen."""
        if self.image:
            tk.Label(parent, image=self.image, bg="black").place(relx=0.5, rely=0.5, anchor="center")
        else:
            tk.Label(
                parent,
                text="\U0001F512\nDieser PC ist gesperrt",
                fg="white",
                bg="black",
                font=("Segoe UI", 48, "bold"),
                justify="center",
            ).place(relx=0.5, rely=0.5, anchor="center")

    def windows_lock_loop(self):
        """Sperrt die Windows-Sitzung und wiederholt das, solange der Status 'locked' bleibt."""
        if not self.locked:
            return
        try:
            ctypes.windll.user32.LockWorkStation()
        except Exception as e:
            print(f"LockWorkStation fehlgeschlagen: {e}")
        relock = int(self.cfg.get("relock_seconds", 30))
        if relock > 0:
            self.root.after(relock * 1000, self.windows_lock_loop)

    def set_locked(self, value):
        if value == self.locked:
            return
        self.locked = value
        self.refresh_tray()
        if value and self.cfg.get("mode", "windows") == "windows" and not self.demo:
            self.windows_lock_loop()
        elif value:
            self.root.deiconify()
            self.span_all_monitors()
            self.root.attributes("-topmost", True)
            self.root.focus_force()
            self.keep_on_top()
        else:
            self.root.withdraw()
            for win in self.extra_windows:
                win.destroy()
            self.extra_windows = []

    def span_all_monitors(self):
        """Ein eigenes Vollbild-Fenster PRO angeschlossenem Monitor, statt einem
        grossen Fenster ueber den virtuellen Gesamt-Desktop: bei Monitoren mit
        unterschiedlicher Windows-Skalierung (z.B. 100% + 125%) berechnet Windows
        sonst Groesse/Position des einen Fensters falsch (z.B. nur halb schwarzer
        Screen auf einem Monitor, der andere ganz unberuehrt)."""
        rects = get_monitor_rects()
        if not rects:
            rects = [(0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())]

        primary = next((r for r in rects if r[0] == 0 and r[1] == 0), rects[0])
        rects = [r for r in rects if r != primary]
        self.place_window(self.root, primary)

        for win in self.extra_windows:
            win.destroy()
        self.extra_windows = []
        for rect in rects:
            win = tk.Toplevel(self.root)
            win.withdraw()  # overrideredirect setzen, BEVOR das Fenster je sichtbar wird
            win.configure(bg="black", cursor="none")
            win.protocol("WM_DELETE_WINDOW", lambda: None)
            win.overrideredirect(True)
            self.add_lock_label(win)
            self.place_window(win, rect)
            win.deiconify()
            self.extra_windows.append(win)

    def place_window(self, win, rect):
        x, y, w, h = rect
        win.geometry(f"{w}x{h}+{x}+{y}")

    def keep_on_top(self):
        if not self.locked:
            return
        for win in [self.root] + self.extra_windows:
            win.attributes("-topmost", True)
            win.lift()
        self.root.focus_force()
        self.root.after(1000, self.keep_on_top)

    def on_escape(self, _event):
        # Notausgang nur im Demo-Modus bzw. wenn in config erlaubt
        if self.demo or self.cfg.get("allow_escape", False):
            self.exit_requested = True

    # ---------- Polling ----------
    def start_fetch(self):
        def worker():
            pc_id = resolve_pc_id(self.cfg)
            try:
                data = fetch_document(self.cfg)
                self.results.put(("ok", str(data.get(self.cfg.get("status_field", "status")))))
                self.apply_install_policy(data.get("install_allowed"))
                self.handle_command(data, pc_id)
            except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
                self.results.put(("err", str(e)))
            finally:
                report(self.cfg, pc_id)

        threading.Thread(target=worker, daemon=True).start()

    def apply_install_policy(self, install_allowed):
        """Setzt bei jedem Poll erneut die Installations-Richtlinie durch (nicht
        nur bei Aenderung) - so wird ein manuell zurueckgedrehter Registry-Wert
        spaetestens beim naechsten Poll wieder korrigiert."""
        allow = install_allowed is not False  # Appwrite-Default/fehlendes Feld -> erlaubt
        if allow != self.last_install_allowed:
            set_install_policy(allow)
            self.last_install_allowed = allow

    def handle_command(self, data, pc_id):
        """Prueft, ob die Lehrkraft im Panel einen neuen Befehl ("command"-Feld)
        hinterlegt hat, und fuehrt ihn aus. Jeder Befehl hat eine eigene 'id',
        damit er nicht bei jedem Poll erneut ausgefuehrt wird."""
        raw = data.get("command")
        if not raw:
            return
        try:
            command = json.loads(raw)
        except (TypeError, ValueError):
            return
        command_id = command.get("id")
        if not command_id or command_id == self.last_command_id:
            return
        self.last_command_id = command_id
        action = command.get("action")
        if action == "list_programs":
            threading.Thread(target=self.run_list_programs, args=(pc_id, command_id), daemon=True).start()
        elif action == "uninstall":
            threading.Thread(
                target=self.run_uninstall, args=(pc_id, command_id, command.get("program_id")), daemon=True
            ).start()
        elif action == "shutdown":
            threading.Thread(target=self.run_shutdown, args=(pc_id, command_id), daemon=True).start()
        elif action == "install":
            threading.Thread(
                target=self.run_install, args=(pc_id, command_id, command.get("package_id")), daemon=True
            ).start()
        elif action == "search_packages":
            threading.Thread(
                target=self.run_search_packages, args=(pc_id, command_id, command.get("query")), daemon=True
            ).start()
        else:
            # Unbekannter Befehl (z.B. Panel ist neuer als dieser laufende Client) -
            # sofort melden und das Feld raeumen, statt es unverarbeitet stehen zu
            # lassen (das Panel wuerde sonst dauerhaft auf eine Antwort warten).
            report(
                self.cfg, pc_id,
                command_result=json.dumps(
                    {"id": command_id, "ok": False, "message": f"Unbekannter Befehl '{action}' - Client neu starten?"}
                ),
                ack_command_id=command_id,
            )

    def run_list_programs(self, pc_id, command_id):
        programs = list_installed_programs()
        self.known_programs = programs
        public_list = [{"id": p["id"], "name": p["name"], "version": p["version"]} for p in programs.values()]
        public_list.sort(key=lambda p: p["name"].lower())
        report(
            self.cfg,
            pc_id,
            programs=json.dumps(public_list),
            command_result=json.dumps({"id": command_id, "ok": True}),
            ack_command_id=command_id,
        )

    def run_install(self, pc_id, command_id, package_id):
        """Installiert ein Programm ueber winget (Windows Package Manager) - bewusst
        NICHT per freier URL/Datei, sondern nur ueber eine winget-Paket-ID aus dessen
        offiziellem, signiertem Repository. Das verhindert, dass ueber das Panel
        beliebiger Code von irgendeiner Adresse automatisch ausgefuehrt werden kann."""
        package_id = (package_id or "").strip()
        if not package_id:
            report(
                self.cfg, pc_id,
                command_result=json.dumps({"id": command_id, "ok": False, "message": "Keine Paket-ID angegeben"}),
                ack_command_id=command_id,
            )
            return
        try:
            result = subprocess.run(
                [
                    "winget", "install", "--id", package_id, "-e", "--silent",
                    "--accept-package-agreements", "--accept-source-agreements",
                ],
                capture_output=True, text=True, timeout=600,
            )
            ok = result.returncode == 0
            message = f"Exit-Code {result.returncode}" if ok else (result.stdout + result.stderr)[-300:]
        except FileNotFoundError:
            ok, message = False, "winget ist auf diesem PC nicht verfuegbar"
        except subprocess.TimeoutExpired:
            ok, message = False, "Zeitlimit bei der Installation ueberschritten"
        except OSError as e:
            ok, message = False, str(e)
        report(
            self.cfg, pc_id,
            command_result=json.dumps({"id": command_id, "ok": ok, "message": message}),
            ack_command_id=command_id,
        )

    def run_search_packages(self, pc_id, command_id, query):
        query = (query or "").strip()
        results = search_winget_packages(query) if query else []
        report(
            self.cfg, pc_id,
            search_results=json.dumps({"query": query, "results": results}),
            command_result=json.dumps({"id": command_id, "ok": True}),
            ack_command_id=command_id,
        )

    def run_uninstall(self, pc_id, command_id, program_id):
        program = self.known_programs.get(program_id)
        if not program:
            # Cache leer (z.B. nach Neustart des Clients) - Registry neu einlesen
            self.known_programs = list_installed_programs()
            program = self.known_programs.get(program_id)
        if not program:
            report(
                self.cfg, pc_id,
                command_result=json.dumps({"id": command_id, "ok": False, "message": "Programm nicht gefunden"}),
                ack_command_id=command_id,
            )
            return
        try:
            result = subprocess.run(program["uninstall_string"], shell=True, timeout=300)
            ok = result.returncode == 0
            message = f"Exit-Code {result.returncode}"
        except subprocess.TimeoutExpired:
            ok, message = False, "Zeitlimit beim Deinstallieren ueberschritten"
        except OSError as e:
            ok, message = False, str(e)
        report(
            self.cfg, pc_id,
            command_result=json.dumps({"id": command_id, "ok": ok, "message": message}),
            ack_command_id=command_id,
        )

    def run_shutdown(self, pc_id, command_id):
        """Faehrt diesen PC herunter. Kurze Verzoegerung, damit die Appwrite-Function
        die Bestaetigung noch zugestellt bekommt, bevor der Rechner ausgeht."""
        try:
            subprocess.run(["shutdown", "/s", "/t", "10"], check=True)
            ok, message = True, "Faehrt in 10 Sekunden herunter"
        except subprocess.CalledProcessError as e:
            ok, message = False, f"shutdown fehlgeschlagen (Exit-Code {e.returncode})"
        except OSError as e:
            ok, message = False, str(e)
        report(
            self.cfg, pc_id,
            command_result=json.dumps({"id": command_id, "ok": ok, "message": message}),
            ack_command_id=command_id,
        )

    def poll_results(self):
        if self.exit_requested:
            self.shutdown()
            return
        try:
            while True:
                kind, value = self.results.get_nowait()
                if kind == "ok":
                    print(f"Status: {value}")
                    self.last_error = None
                    self.set_locked(value == str(self.cfg.get("lock_value", "locked")))
                else:
                    # Bei Netzwerkfehler Zustand beibehalten, nur Status im Tray zeigen
                    print(f"Fehler beim Abruf: {value}")
                    self.last_error = value
                    self.refresh_tray()
                if not self.demo:
                    self.root.after(int(self.cfg.get("poll_seconds", 5)) * 1000, self.start_fetch)
        except queue.Empty:
            pass
        self.root.after(200, self.poll_results)

    def shutdown(self):
        try:
            self.icon.stop()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# Autostart - geplante Aufgabe statt Startup-Ordner, damit pc_manager.py
# ERHOEHT (elevated) starten kann: die Installations-Sperre (HKCU\...\Policies)
# ist selbst fuer den eigenen Nutzer ohne erhoehte Rechte gesperrt. "Sichtbar"
# bleibt es trotzdem - einsehbar in der Aufgabenplanung (taskschd.msc), kein
# Versteckspiel.
# ---------------------------------------------------------------------------

def pythonw_path():
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def install_autostart():
    """Muss EINMALIG als Administrator ausgefuehrt werden: Windows erlaubt
    geplante Aufgaben mit '/rl highest' (erhoehten Rechten) nur fuer Admins
    einzurichten. Danach startet die Aufgabe bei jeder Anmeldung erhoeht,
    OHNE weitere UAC-Abfrage."""
    target = pythonw_path()
    # Mit launcher.py (Auto-Update) starten, falls vorhanden.
    launcher = BASE / "launcher.py"
    script = launcher if launcher.exists() else SCRIPT_FILE
    command = f'"{target}" "{script}"'
    args = [
        "schtasks", "/create", "/tn", AUTOSTART_TASK_NAME,
        "/tr", command,
        "/sc", "onlogon",
        "/rl", "highest",
        "/f",
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(
            "Autostart konnte nicht eingerichtet werden. Dieser Befehl muss als "
            "Administrator ausgefuehrt werden (Rechtsklick auf die Eingabeaufforderung "
            "> 'Als Administrator ausfuehren'):\n" + (result.stderr or result.stdout)
        )
    print(f"Autostart eingerichtet: geplante Aufgabe '{AUTOSTART_TASK_NAME}' (startet erhoeht bei jeder Anmeldung).")
    print("Sichtbar in der Aufgabenplanung (taskschd.msc).")


def uninstall_autostart():
    result = subprocess.run(
        ["schtasks", "/delete", "/tn", AUTOSTART_TASK_NAME, "/f"], capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"Autostart entfernt: geplante Aufgabe '{AUTOSTART_TASK_NAME}'")
    else:
        print("Keine Autostart-Aufgabe gefunden.")


def main():
    enable_per_monitor_dpi_awareness()

    if "--install-autostart" in sys.argv:
        install_autostart()
        return
    if "--uninstall-autostart" in sys.argv:
        uninstall_autostart()
        return

    demo = "--demo" in sys.argv
    if demo:
        cfg = {}
        if CONFIG_FILE.exists():
            cfg = load_config()
    else:
        if not CONFIG_FILE.exists():
            sys.exit("config.json fehlt - siehe config.example.json")
        cfg = load_config()
    LockApp(cfg, demo=demo).run()


if __name__ == "__main__":
    main()
