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

## Modi (`mode` in config.json)
- `windows` (Standard): echte Windows-Sperre wie Win+L. Entsperrt wird mit PIN/Passwort. Bleibt der Status `locked`, sperrt das Programm alle `relock_seconds` (Standard 30, `0` = nur einmal) erneut.
- `overlay`: Vollbild-Fenster mit `lock.png`, keine echte Sperre (per Strg+Alt+Entf / Task-Manager umgehbar).

`--demo` nutzt immer das Overlay, damit du dich nicht aussperrst.

**Achtung:** Zum Entsperren braucht man das Windows-Passwort/PIN. Setze den Status in Appwrite wieder auf etwas anderes als `locked`, sonst sperrt sich der PC nach dem Entsperren erneut.
