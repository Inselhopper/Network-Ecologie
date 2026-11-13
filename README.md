# Network Ecologie

Sequenzieller Prototyp der interaktiven Mundinstallation. Arduino und Servo werden
zurzeit ausschließlich simuliert. Es wird kein serieller Port geöffnet.
Das Kamerafenster zeigt den virtuellen Mund, den geglätteten Winkel (35–95 Grad),
den Zustand und die jeweils zuständige Bewegungsquelle.

## Start

Im Ordner `Network-Ecologie`:

```powershell
.\.venv\Scripts\python.exe network_ecologie.py
```

ESC im Kamerafenster oder Strg+C beendet das Programm.

```powershell
.\.venv\Scripts\python.exe network_ecologie.py --list-devices
.\.venv\Scripts\python.exe network_ecologie.py --input-device 14 --output-device 12
.\.venv\Scripts\python.exe network_ecologie.py --threshold 0.015 --max-record 4
```

Gerätenummern sind Beispiele. Benötigt werden die bereits vorhandenen Pakete
NumPy, sounddevice, OpenCV und MediaPipe mit `mp.solutions.face_mesh`.
Die kopierte `venv` verweist auf einen anderen Benutzerpfad und startet hier
nicht. Für diesen Prototyp wird eine eigene `.venv` mit Python 3.11 verwendet.
Bei einer späteren Neueinrichtung: `python -m venv .venv`, anschließend
`.\.venv\Scripts\python.exe -m pip install -r requirements-network.txt`.

Softwareprüfung ohne Kamera, Mikrofon oder Arduino:
`.\.venv\Scripts\python.exe check_prototype.py`.

## Ablauf und Erprobung

1. `LISTENING`: kurze Phrase sprechen oder summen. Die RMS-Schwelle ist zunächst
   0.025; bei leiser Stimme `--threshold` verkleinern, bei Raumgeräuschen erhöhen.
2. `RECORDING_HUMAN`: Aufnahme bis 0.7 Sekunden Stille, höchstens vier Sekunden.
   FaceMesh-Winkel werden mit relativen Zeitstempeln gespeichert. Der virtuelle
   Servo bleibt bei 35 Grad. Es gibt keine Stimmvorlaufaufnahme; der erste
   Auslöseblock ist enthalten, ein leiser Wortanfang kann fehlen.
3. `PROCESSING_RESPONSE` / `PLAYBACK_RESPONSE`: Ein leises, kurzes Echo verändert
   die Stimme bei unveränderter Länge. Die gespeicherte Bewegung folgt der
   Wiedergabezeit des Audiogeräts. Fehlendes Gesicht ergibt eine Ruheposition.
4. `INVITATION_PAUSE`: 1.5 Sekunden Pause, dann `WAITING_FOR_RESPONSE` mit acht
   Sekunden Reaktionszeit. Stimme oder geöffneter Mund startet das gemeinsame
   Spiel. Ohne Reaktion kehrt das System über `FADE_OUT` zum Zuhören zurück.
5. `SYNCHRONOUS_PLAY`: acht Sekunden leiser Loop der Antwort; FaceMesh steuert
   den virtuellen Mund live. Die reale Stimme mischt sich akustisch im Raum.
6. `MACHINE_LEADS`: Eine aus vier Aufnahmeteilen neu angeordnete Phrase spielt.
   Die Audio-Lautstärke steuert den Mund, FaceMesh hat keinen Steuereinfluss.
7. `HUMAN_JOINS`: Zwei Wiederholungen laden zum Mitmachen ein. Eine Mundöffnung
   wird als Beteiligung protokolliert; musikalisches Folgen wird nicht bewertet.
   Danach klingt die Phrase aus und der Mund fährt in zwei Sekunden zur Ruhe.

Während Maschinenklang und Einladungspause werden Mikrofonblöcke verworfen.
Damit kann die Wiedergabe selbst keine neue Aufnahme starten. Langer Raumhall
kann nach der Pause trotzdem die Schwelle überschreiten; die Aufstellung und
Schwelle müssen am tatsächlichen Ort getestet werden.

Audioeffekte laufen in einem Arbeitsthread, Audio-I/O in PortAudio-Callbacks.
Die Kamera läuft im Hauptthread. Bewegung und Audiowiedergabe teilen eine
monotone Zeitbasis; Kamera-Bildrate, Geräte und mechanische Trägheit begrenzen
die tatsächliche Synchronität. Die Simulation belegt keine Hardware-Synchronität.

Alle Aufnahmen und Bewegungsdaten bleiben im RAM und werden beim Zyklusende
oder Beenden freigegeben. Zustände, Aufnahmedauer, Wiedergaben, Beteiligung und
Fehler erscheinen mit Zeitstempel im Terminal; es entstehen keine Audiodateien.

## Bestehender Code

`camera.py` und `mouth_detector.py` werden wiederverwendet. `network_ecologie.py`
enthält den neuen Einstieg, die Zustandssteuerung und die Simulation.
`main.py`, `servo_controller.py`, die Arduino-Firmware und die bisherigen
Echtzeitaudio-Experimente bleiben als alter Prototyp erhalten. `main.py` startet
weiterhin den alten Ablauf und ist **nicht** der Einstieg für diese Simulation.
Mehrere Servos, automatische Musikanalyse und echte Hardwareansteuerung sind
noch nicht implementiert.
