"""Kleiner Webserver fuer das Lehrer-Panel, laeuft ohne Konsolenfenster (pythonw).

Start:  pythonw serve_panel.pyw [PORT] [BIND]
        Standard: Port 8080, nur lokal erreichbar (127.0.0.1).
        Fuer Zugriff aus dem Netz: pythonw serve_panel.pyw 8080 0.0.0.0

Hinweis: Unter pythonw gibt es kein stderr, "python -m http.server" bricht dort
beim Loggen jeder Anfrage ab. Darum wird die Ausgabe hier verworfen.
"""
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
bind = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"

sys.stdout = sys.stderr = open(os.devnull, "w")

handler = partial(SimpleHTTPRequestHandler, directory=BASE)
ThreadingHTTPServer((bind, port), handler).serve_forever()
