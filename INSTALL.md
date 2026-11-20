# Installation auf einem frischen Windows-PC

Es gibt zwei Teile:

- **Lehrer-Panel** (`teacher-panel.html`): statische HTML-Datei, die direkt mit Appwrite (`appwrite.buchholz.dev`) spricht. Braucht nur einen kleinen Webserver.
- **Schüler-PCs** (`pc_manager.py`): Tray-Programm, das den Status aus Appwrite abfragt und den PC sperrt.

Einen eigenen Backend-Server gibt es nicht.

## 1. Python und Git installieren

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
```

Danach ein neues PowerShell-Fenster öffnen, damit `python` und `git` gefunden werden.

## 2. Repo holen

```powershell
git clone https://github.com/Benspiel/pc-manager.git
cd pc-manager
```

## 3. Lehrer-Panel: Webserver starten

```powershell
python -m http.server 8080
```

Dann im Browser `http://localhost:8080/teacher-panel.html` öffnen.

Soll das Panel von anderen Rechnern im Netz erreichbar sein:

```powershell
python -m http.server 8080 --bind 0.0.0.0
```

und Port 8080 in der Windows-Firewall erlauben.

## 4. Appwrite-Plattform freigeben

Die Datei **nicht** per Doppelklick (`file://`) öffnen, sonst blockiert Appwrite die Anfragen per CORS.

Im Appwrite-Projekt unter **Übersicht → Plattformen → Web-App hinzufügen** den Hostnamen eintragen, über den das Panel aufgerufen wird:

- lokal: `localhost`
- im Netz: Hostname oder IP des Server-PCs

## 5. Im Panel anmelden

Endpoint (`https://appwrite.buchholz.dev/v1`) und Projekt-ID (`6af62636001a129b6298`) sind voreingestellt.

Anmelden muss ein Benutzer im Appwrite-Team `lehrer`, denn nur dieses Team hat Schreibrechte auf die Collection `pc`.

## 6. Schüler-PCs einrichten

Auf jedem Schüler-PC (Python und Repo wie oben installieren):

```powershell
pip install pystray pillow
copy config.example.json config.json
```

In `config.json` Endpoint und Projekt-ID eintragen. Die Zeile in Appwrite wird über `pc_id` bestimmt, ohne Eintrag wird der Hostname des Rechners verwendet.

Testen, ohne sich auszusperren (Esc beendet):

```powershell
python pc_manager.py --demo
```

Autostart einrichten (als **Administrator** ausführen):

```powershell
python pc_manager.py --install-autostart
```

Entfernen:

```powershell
python pc_manager.py --uninstall-autostart
```

Weitere Details zu Modi und Konfiguration stehen in der [README](README.md).
