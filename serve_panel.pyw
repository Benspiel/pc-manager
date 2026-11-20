"""Kleiner Webserver fuer das Lehrer-Panel, laeuft ohne Konsolenfenster (pythonw).

Start:  pythonw serve_panel.pyw [PORT] [BIND]
        Standard: Port 8080, nur lokal erreichbar (127.0.0.1).
        Fuer Zugriff aus dem Netz: pythonw serve_panel.pyw 8080 0.0.0.0

Auto-Update: Der Server holt beim Start und danach regelmaessig (config.json:
"update_check_minutes", Standard 30) die neueste Version aus dem oeffentlichen
GitHub-Repo (gleiche Logik wie launcher.py, kein API-Key noetig). Das Panel ist
nur eine HTML-Datei, neue Versionen sind also nach einem Neuladen der Seite
aktiv. Aendert sich dieses Skript selbst, startet sich der Server neu.
Abschalten: "auto_update": false in config.json.

Hinweis: Unter pythonw gibt es kein stderr, "python -m http.server" bricht dort
beim Loggen jeder Anfrage ab. Darum wird die Ausgabe hier verworfen.
"""
import hashlib
import os
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
bind = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"

sys.stdout = sys.stderr = open(os.devnull, "w")


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Nach einem Update soll der Browser nicht die alte Seite aus dem Cache zeigen.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def code_hash():
    h = hashlib.sha1()
    for name in ("serve_panel.pyw", "launcher.py"):
        try:
            with open(os.path.join(BASE, name), "rb") as f:
                h.update(f.read())
        except OSError:
            pass
    return h.hexdigest()


restart_requested = threading.Event()


def update_loop(server):
    try:
        sys.path.insert(0, BASE)
        import launcher
    except Exception:
        return  # ohne launcher.py kein Auto-Update, der Server laeuft trotzdem
    while True:
        try:
            before = code_hash()
            if launcher.update_if_needed() and code_hash() != before:
                # Der Server-Code selbst hat sich geaendert: Neustart (macht der Hauptthread).
                restart_requested.set()
                server.shutdown()
                return
            minutes = max(1, int(launcher.load_config().get("update_check_minutes", 30) or 30))
        except Exception:
            minutes = 30
        time.sleep(minutes * 60)


handler = partial(Handler, directory=BASE)
server = ThreadingHTTPServer((bind, port), handler)
threading.Thread(target=update_loop, args=(server,), daemon=True).start()
server.serve_forever()
server.server_close()
if restart_requested.is_set():
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
    subprocess.Popen(
        [sys.executable, os.path.join(BASE, "serve_panel.pyw"), str(port), bind],
        cwd=BASE, creationflags=flags,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
