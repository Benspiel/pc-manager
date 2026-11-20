# PC-Manager

Fragt alle paar Sekunden ein Appwrite-Dokument ab. Steht das Feld `status` auf `locked`, wird ein Vollbild-Sperrbildschirm angezeigt – sonst bleibt alles unsichtbar.

## Einrichten
1. In Appwrite eine Collection mit einem String-Attribut `status` anlegen und ein Dokument erstellen (z. B. `status = "unlocked"`).
2. Leseberechtigung: entweder dem Dokument/der Collection `Read: Any` geben **oder** einen API-Key mit `documents.read` in `config.json` eintragen.
3. `config.example.json` nach `config.json` kopieren und die IDs eintragen.
4. Optional: ein Bild `lock.png` (PNG/GIF) in diesen Ordner legen – wird als Sperrbild angezeigt.
5. Abhängigkeiten installieren (für das Tray-Icon):
   ```
   pip install pystray pillow
   ```

## Starten
```
python pc_manager.py          # mit Konsolenfenster
pythonw pc_manager.py         # ohne Konsolenfenster (normaler Hintergrundbetrieb)
python pc_manager.py --demo   # Sperrbild sofort testen, Esc beendet
```
Das Programm läuft als ganz normales Tray-Programm: Icon unten rechts im
Infobereich der Taskleiste (grün = verbunden, rot = Fehler beim Abruf, grau =
startet gerade). Rechtsklick zeigt den Status (verbunden/Fehler, gesperrt/
entsperrt) und **Beenden** – das beendet das Programm wirklich, kein
automatischer Neustart, kein Verstecken vor Task-Manager oder Autostart-Liste.

## Autostart
```
python pc_manager.py --install-autostart     # legt eine Verknüpfung in shell:startup an
python pc_manager.py --uninstall-autostart    # entfernt sie wieder
```
Der Eintrag heißt `PC-Manager` und ist ganz normal sichtbar unter
**Windows-Einstellungen → Apps → Autostart** bzw. im Task-Manager unter dem
Tab „Autostart". Startet mit `pythonw.exe`, also ohne Konsolenfenster.

## Selbstregistrierung
Ein PC, zu dem es in Appwrite noch keine Zeile gibt, legt sie beim ersten Verbinden selbst an: Der Client ruft die `heartbeat`-Function mit `register: true` auf, und die Function erstellt die Zeile (`pc_id` = Hostname bzw. `pc_id` aus der `config.json`, `status` = `unlocked`, `pc_name` = Hostname, `last_seen`). Raum (`room`) trägst du danach im Panel ein. `provision_pcs.py` ist damit nur noch nötig, wenn du Räume/Namen vorab per CSV setzen willst.

- Bestehende Zeilen werden dadurch nie verändert, der Sperrstatus kann so nicht umgangen werden.
- Schutz vor Missbrauch (die Function darf jeder aufrufen): erlaubt sind nur IDs aus Buchstaben, Zahlen, `.`, `_`, `-` (max. 36 Zeichen), und es gibt eine Obergrenze von 500 Zeilen (Function-Variable `MAX_PCS`).
- Der Client versucht es höchstens alle 5 Minuten. Abschalten mit `"auto_register": false` in der `config.json`.
- Die geänderte Function muss einmalig neu deployt werden: `appwrite push functions` (Funktion `heartbeat`).

## Auto-Update
`launcher.py` startet `pc_manager.py` und holt sich selbst die neueste Version aus dem öffentlichen GitHub-Repo – ohne API-Key. Der Autostart (`--install-autostart`) startet automatisch den Launcher, falls `launcher.py` vorhanden ist.

- Beim Start wird auf einen neueren Commit geprüft, danach alle `update_check_minutes` (Standard 30). Bei einem neuen Commit wird die Version geladen, geprüft (muss kompilieren) und `pc_manager.py` automatisch neu gestartet.
- `config.json` wird nie überschrieben. Die installierte Version steht in `.version`, Meldungen in `launcher.log`.
- Beendet sich `pc_manager.py` (Tray → Beenden oder Absturz), beendet sich auch der Launcher – kein automatischer Neustart. Beim nächsten Anmelden wird zuerst aktualisiert.
- Abschalten: `"auto_update": false` in `config.json`.
- **Sicherheit:** Wer in das GitHub-Repo pushen darf, führt damit Code auf allen PCs aus (erhöht). Das GitHub-Konto mit 2FA absichern.

## Modi (`mode` in config.json)
- `windows` (Standard): echte Windows-Sperre wie Win+L. Entsperrt wird mit PIN/Passwort. Bleibt der Status `locked`, sperrt das Programm alle `relock_seconds` (Standard 30, `0` = nur einmal) erneut.
- `overlay`: Vollbild-Fenster mit `lock.png`, keine echte Sperre (per Strg+Alt+Entf / Task-Manager umgehbar).

`--demo` nutzt immer das Overlay, damit du dich nicht aussperrst.

**Achtung:** Zum Entsperren braucht man das Windows-Passwort/PIN. Setze den Status in Appwrite wieder auf etwas anderes als `locked`, sonst sperrt sich der PC nach dem Entsperren erneut.
