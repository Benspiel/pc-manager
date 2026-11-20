"""Appwrite-Function: Lebenszeichen + Status-Reports eines PC-Manager-Clients.

Der Client (pc_manager.py) hat bewusst KEINE Schreibrechte auf die "pc"-Tabelle
(nur Lehrer duerfen sperren/entsperren/Befehle erteilen). Trotzdem muss der
Client melden koennen: dass er laeuft (last_seen), welche Programme installiert
sind (programs) und ob ein Befehl erfolgreich war (command_result). Diese
Function ist der einzige erlaubte Schreibweg dafuer: sie setzt IMMER last_seen
und darueber hinaus NUR die explizit erlaubten Felder unten - niemals "status",
"room" oder "pc_name". Ein Student, der die Function direkt mit anderen Daten
aufruft, kann also nie den Sperrstatus veraendern.

Ausfuehrungsrechte: any (jeder darf die Function aufrufen, auch ohne Login) -
das ist in Ordnung, weil die Function selbst nur die Felder unten schreiben kann.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

DATABASE_ID = "main"
TABLE_ID = "pc"
# Nur diese Felder darf der Client ueber diese Function setzen (zusaetzlich zu
# last_seen, das immer gesetzt wird). Alles andere wird ignoriert.
ALLOWED_REPORT_FIELDS = {"programs", "command_result", "search_results"}
MAX_FIELD_LENGTH = 16000


def main(context):
    try:
        body = context.req.body_json if context.req.body_json else json.loads(context.req.body or "{}")
    except (ValueError, TypeError):
        body = {}

    pc_id = str(body.get("pc_id", "")).strip()
    if not pc_id:
        return context.res.json({"ok": False, "error": "pc_id fehlt"}, 400)

    endpoint = os.environ.get("APPWRITE_FUNCTION_API_ENDPOINT")
    project_id = os.environ.get("APPWRITE_FUNCTION_PROJECT_ID")
    # Diese Appwrite-Version stellt keinen dynamischen Function-API-Key bereit
    # (kein APPWRITE_FUNCTION_API_KEY) - deshalb ein eigener, nur fuer diese
    # Function sichtbarer Key als Variable "HEARTBEAT_API_KEY" (Scope nur
    # databases.write), in der Appwrite-Console unter Functions > heartbeat >
    # Variables gesetzt.
    api_key = os.environ.get("HEARTBEAT_API_KEY")
    if not api_key:
        context.error("HEARTBEAT_API_KEY Variable fehlt auf der Function")
        return context.res.json({"ok": False, "error": "Function nicht konfiguriert"}, 500)

    data = {"last_seen": datetime.now(timezone.utc).isoformat()}
    for key in ALLOWED_REPORT_FIELDS:
        if key in body:
            data[key] = str(body[key])[:MAX_FIELD_LENGTH]

    doc_url = (
        f"{endpoint.rstrip('/')}/databases/{DATABASE_ID}"
        f"/collections/{TABLE_ID}/documents/{pc_id}"
    )
    headers = {
        "Content-Type": "application/json",
        "X-Appwrite-Project": project_id,
        "X-Appwrite-Key": api_key,
        "User-Agent": "pc-manager-heartbeat/1.0",  # Standard-Python-UA wird von Cloudflare geblockt (403)
    }

    # Das "command"-Feld nur raeumen, wenn dort immer noch GENAU der Befehl steht,
    # den dieser Client gerade abgearbeitet hat. Sonst Race Condition: Lehrkraft
    # tippt schon den naechsten Befehl, waehrend der vorherige noch laeuft - ein
    # blindes Leeren wuerde den neuen, noch unbearbeiteten Befehl verschlucken.
    ack_command_id = body.get("ack_command_id")
    if ack_command_id:
        get_req = urllib.request.Request(doc_url, headers=headers)
        try:
            with urllib.request.urlopen(get_req, timeout=10) as resp:
                current = json.load(resp)
            current_command = json.loads(current.get("command") or "{}")
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError, OSError):
            current_command = {}
        if current_command.get("id") == ack_command_id:
            data["command"] = ""

    payload = json.dumps({"data": data}).encode()
    req = urllib.request.Request(doc_url, data=payload, method="PATCH")
    for name, value in headers.items():
        req.add_header(name, value)

    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return context.res.json({"ok": False, "error": "PC-ID unbekannt"}, 404)
        context.error(f"Appwrite-Fehler {e.code}: {e.read()}")
        return context.res.json({"ok": False, "error": "Appwrite-Fehler"}, 502)

    return context.res.json({"ok": True})
