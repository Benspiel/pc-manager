"""Legt in Appwrite fuer jeden Schul-PC aus einer CSV-Liste eine Zeile an (oder
aktualisiert sie), damit pc_manager.py auf dem jeweiligen Rechner einen eigenen
Status findet.

CSV-Format (Kopfzeile Pflicht), siehe pcs.example.csv:
    pc_id,room,pc_name
    INFO-PC01,Informatik-Raum,PC 1

pc_id muss exakt dem Hostnamen des jeweiligen Rechners entsprechen (oder dem
"pc_id" in dessen config.json), sonst findet pc_manager.py die Zeile nicht.

Nutzt die bereits eingeloggte Appwrite-CLI (appwrite login) - kein API-Key im
Klartext hier noetig.

Aufruf:
    python provision_pcs.py pcs.csv
"""
import csv
import json
import subprocess
import sys

DATABASE_ID = "main"
TABLE_ID = "pc"


def run_appwrite(args):
    result = subprocess.run(
        ["appwrite", *args, "--json"], capture_output=True, text=True
    )
    return result.returncode, result.stdout, result.stderr


def upsert_row(pc_id, room, pc_name):
    data = json.dumps({"status": "unlocked", "room": room, "pc_name": pc_name})
    code, out, err = run_appwrite(
        [
            "tablesdb", "create-row",
            "--database-id", DATABASE_ID,
            "--table-id", TABLE_ID,
            "--row-id", pc_id,
            "--data", data,
        ]
    )
    if code == 0:
        print(f"[neu]      {pc_id} ({room})")
        return
    # Zeile existiert schon -> aktualisieren statt anlegen
    code2, out2, err2 = run_appwrite(
        [
            "tablesdb", "update-row",
            "--database-id", DATABASE_ID,
            "--table-id", TABLE_ID,
            "--row-id", pc_id,
            "--data", json.dumps({"room": room, "pc_name": pc_name}),
        ]
    )
    if code2 == 0:
        print(f"[aktualisiert] {pc_id} ({room})")
    else:
        print(f"[FEHLER]   {pc_id}: {err or err2}")


def main():
    if len(sys.argv) != 2:
        sys.exit("Aufruf: python provision_pcs.py <csv-datei>")
    with open(sys.argv[1], newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            upsert_row(row["pc_id"].strip(), row.get("room", "").strip(), row.get("pc_name", "").strip())


if __name__ == "__main__":
    main()
