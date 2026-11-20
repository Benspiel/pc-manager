# Installation auf einem frischen Windows-PC

Es gibt zwei Teile:

- **Lehrer-Panel** (`teacher-panel.html`): statische HTML-Datei, die direkt mit Appwrite (`appwrite.buchholz.dev`) spricht. Braucht nur einen kleinen Webserver.
- **Schüler-PCs** (`pc_manager.py`): Tray-Programm, das den Status aus Appwrite abfragt und den PC sperrt.

Einen eigenen Backend-Server gibt es nicht.

## Schnellstart für Schüler-PCs (ein Skript)

Nur Python muss installiert sein (`winget install -e --id Python.Python.3.12`). Dann [setup.py](setup.py) herunterladen und ausführen:

```powershell
python setup.py
```

Das Skript lädt das Projekt von GitHub nach `C:\ProgramData\PC-Manager`, installiert `pystray` und `pillow`, legt eine `config.json` an (`pc_id` leer, also gilt der Hostname), richtet den Autostart ein und startet das Programm. Für den Autostart fragt es per UAC nach Administratorrechten. Danach aktualisiert sich das Programm selbst: `launcher.py` prüft beim Start und alle 30 Minuten auf einen neuen Commit im GitHub-Repo (kein API-Key nötig, das Repo ist öffentlich) und startet mit der neuen Version neu. `setup.py` muss pro PC nur einmal laufen. Details und Abschalten (`auto_update`) stehen in der [README](README.md).

Optionen: `--dir ORDNER`, `--pc-id NAME`, `--no-autostart` (dann kein Admin nötig), `--no-start`.

Die Schritte unten beschreiben die manuelle Einrichtung und das Lehrer-Panel.

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

## 4. Webserver im Hintergrund laufen lassen

Mit `python -m http.server` bleibt ein Konsolenfenster offen, und der Server endet, sobald es geschlossen wird. Außerdem funktioniert `pythonw -m http.server` **nicht**: Der Server lauscht zwar, beantwortet aber keine Anfragen, weil `pythonw` kein Fehlerausgabe-Fenster hat. Darum liegt im Repo das Skript `serve_panel.pyw`, das ohne Fenster läuft.

**Einmal ohne Fenster starten** (läuft bis zum Abmelden oder Neustart), im Repo-Ordner:

```powershell
Start-Process pythonw -ArgumentList "serve_panel.pyw" -WindowStyle Hidden
```

Standard ist Port 8080, nur auf diesem PC erreichbar. Für den Zugriff aus dem Netz (Port 8080 in der Firewall freigeben):

```powershell
Start-Process pythonw -ArgumentList "serve_panel.pyw 8080 0.0.0.0" -WindowStyle Hidden
```

**Automatisch bei jeder Anmeldung starten** (Verknüpfung im Autostart-Ordner, ohne Administratorrechte), im Repo-Ordner:

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PC-Manager-Panel.lnk")
$s.TargetPath = (Get-Command pythonw).Source
$s.Arguments = "`"$PWD\serve_panel.pyw`""
$s.WorkingDirectory = "$PWD"
$s.WindowStyle = 7
$s.Save()
```

Der Server startet dann nach jeder Anmeldung des Benutzers automatisch und ohne sichtbares Fenster. Für den Zugriff aus dem Netz hängst du in `Arguments` ` 8080 0.0.0.0` hinter den Skriptpfad.

Prüfen, ob der Server läuft (Antwort `200`):

```powershell
curl.exe -s -o NUL -w "%{http_code}" http://localhost:8080/teacher-panel.html
```

Beenden:

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object CommandLine -match "serve_panel" | ForEach-Object { Stop-Process -Id $_.ProcessId }
```

Autostart wieder entfernen:

```powershell
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PC-Manager-Panel.lnk"
```

## 5. Appwrite-Plattform freigeben

Die Datei **nicht** per Doppelklick (`file://`) öffnen, sonst blockiert Appwrite die Anfragen per CORS.

Im Appwrite-Projekt unter **Übersicht → Plattformen → Web-App hinzufügen** den Hostnamen eintragen, über den das Panel aufgerufen wird:

- lokal: `localhost`
- im Netz: Hostname oder IP des Server-PCs

## 6. Im Panel anmelden

Endpoint (`https://appwrite.buchholz.dev/v1`) und Projekt-ID (`6af62636001a129b6298`) sind voreingestellt.

Anmelden muss ein Benutzer im Appwrite-Team `lehrer`, denn nur dieses Team hat Schreibrechte auf die Collection `pc`.

## 7. Schüler-PCs einrichten

Auf jedem Schüler-PC (Python und Repo wie oben installieren):

```powershell
pip install pystray pillow
copy config.example.json config.json
```

In `config.json` Endpoint und Projekt-ID eintragen. Die Zeile in Appwrite wird über `pc_id` bestimmt, ohne Eintrag wird der Hostname des Rechners verwendet. Gibt es die Zeile noch nicht, legt der PC sie beim ersten Verbinden selbst an (siehe [README](README.md), Abschnitt Selbstregistrierung).

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







Microsoft Windows [Version 10.0.26200.9457]
(c) Microsoft Corporation. Alle Rechte vorbehalten.

C:\Users\User>C:\Users\User\Documents\pc-manager
Der Befehl "C:\Users\User\Documents\pc-manager" ist entweder falsch geschrieben oder
konnte nicht gefunden werden.

C:\Users\User>cd C:\Users\User\Documents\pc-manager

C:\Users\User\Documents\pc-manager>$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\PC-Manager-Panel.lnk")
Der Befehl "$s" ist entweder falsch geschrieben oder
konnte nicht gefunden werden.

C:\Users\User\Documents\pc-manager>$s.TargetPath = (Get-Command pythonw).Source
Der Befehl "$s.TargetPath" ist entweder falsch geschrieben oder
konnte nicht gefunden werden.

C:\Users\User\Documents\pc-manager>$s.Arguments = "`"$PWD\serve_panel.pyw`""
Der Befehl "$s.Arguments" ist entweder falsch geschrieben oder
konnte nicht gefunden werden.

C:\Users\User\Documents\pc-manager>$s.WorkingDirectory = "$PWD"
Der Befehl "$s.WorkingDirectory" ist entweder falsch geschrieben oder
konnte nicht gefunden werden.

C:\Users\User\Documents\pc-manager>$s.WindowStyle = 7
Der Befehl "$s.WindowStyle" ist entweder falsch geschrieben oder
konnte nicht gefunden werden.

C:\Users\User\Documents\pc-manager>$s.Save()
