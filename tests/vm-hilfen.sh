# shellcheck shell=bash
# =============================================================================
# hermes-os -- Hilfen, um die Plasma-Sitzung der Test-VM per SSH zu bedienen
# =============================================================================
# In die VM kopieren und in einer SSH-Sitzung einlesen, als der Nutzer, der
# grafisch angemeldet ist (die Umgebung folgt seiner UID):
#   sed 's/\r$//' tests/vm-hilfen.sh | ssh <nutzer>@<vm> 'cat > ~/hosenv.sh'
#   ssh <nutzer>@<vm>, dann:  . ~/hosenv.sh
# Das Passwort der VM kommt aus VM_PASS (nie ins Repo schreiben); nur prep
# braucht es, für sudo. Hat der angemeldete Nutzer kein sudo (Nutzer demo für
# den Clip), läuft prep einmal als Admin-Nutzer und flach danach als demo.
#
#   wake            Sperre aufheben, Anzeige einschalten (sonst altes oder schwarzes Bild)
#   shot [DATEI]    Bildschirmfoto der ganzen Sitzung, Vorgabe ~/hos/s.png
#   shotp [DATEI]   dasselbe mit Mauszeiger
#   prep            ydotool-Daemon starten (sudo), dann flach
#   flach           Zeigerbeschleunigung des ydotool-Geräts in dieser Sitzung abschalten
#   click X Y       Linksklick an Bildschirmkoordinaten (braucht prep)
#   rec_start [X Y] Bildschirmaufnahme mit Spectacle starten (braucht prep)
#   rec_stop        Aufnahme beenden, Pfad der neuen Datei ausgeben
#   paste TEXT      Text über die Zwischenablage einfügen (ydotool type kennt nur US-Belegung)
#   frage TEXT      Frage über den Runner des Leisten-Symbols ins Kontor
#   frage_still T   dasselbe ohne Fenster, Antwort als Benachrichtigung
# Beschreibung und Stolperfallen: docs/testumgebung.md, „VM 112 von hier bedienen“.
# =============================================================================

export XDG_RUNTIME_DIR="/run/user/$(id -u)" WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 \
       DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" QT_QPA_PLATFORM=wayland
export YDOTOOL_SOCKET=/tmp/.ydotool_socket
mkdir -p ~/hos

wake() {
  loginctl unlock-session "$(loginctl list-sessions --no-legend | awk '$4=="seat0"{print $1}')" 2>/dev/null
  systemd-run --user -q --wait kscreen-doctor --dpms on >/dev/null 2>&1
  sleep 1
}

shot() {
  local out="${1:-$HOME/hos/s.png}"
  wake
  rm -f "$out"
  timeout 20 spectacle -b -n -f -o "$out" >/dev/null 2>&1
  ls "$out" >/dev/null
}

shotp() {
  local out="${1:-$HOME/hos/s.png}"
  wake
  rm -f "$out"
  timeout 20 spectacle -b -n -f -p -o "$out" >/dev/null 2>&1
  ls "$out" >/dev/null
}

prep() {
  if [ -z "${VM_PASS:-}" ]; then
    echo "VM_PASS fehlt (Passwort der VM für sudo)"
    return 1
  fi
  echo "$VM_PASS" | sudo -S -p "" systemctl start ydotool
  sleep 1
  echo "$VM_PASS" | sudo -S -p "" chmod 666 /tmp/.ydotool_socket
  flach
}

# Nur in der angemeldeten Sitzung wirksam: ohne grafische Sitzung dieses
# Nutzers findet die Schleife kein KWin
flach() {
  local d
  for d in $(gdbus call --session -d org.kde.KWin -o /org/kde/KWin/InputDevice \
               -m org.freedesktop.DBus.Properties.Get org.kde.KWin.InputDeviceManager devicesSysNames \
             | grep -o "event[0-9]*"); do
    if gdbus call --session -d org.kde.KWin -o "/org/kde/KWin/InputDevice/$d" \
         -m org.freedesktop.DBus.Properties.Get org.kde.KWin.InputDevice name | grep -q ydotoold; then
      gdbus call --session -d org.kde.KWin -o "/org/kde/KWin/InputDevice/$d" -m org.freedesktop.DBus.Properties.Set \
        org.kde.KWin.InputDevice pointerAccelerationProfileFlat "<true>" >/dev/null
      gdbus call --session -d org.kde.KWin -o "/org/kde/KWin/InputDevice/$d" -m org.freedesktop.DBus.Properties.Set \
        org.kde.KWin.InputDevice pointerAcceleration "<0.0>" >/dev/null
      echo "flach: $d"
    fi
  done
}

# Erst weit nach links oben, dann relativ: so ist die Position unabhängig vom Stand davor.
# Drücken und Loslassen getrennt: ein 0xC0 in einem Zug übersieht zum Beispiel
# Spectacles Bildschirmwahl
click() {
  ydotool mousemove -x -4000 -y -4000 >/dev/null
  sleep 0.2
  ydotool mousemove -x "$1" -y "$2" >/dev/null
  sleep 0.3
  ydotool click 0x40 >/dev/null
  sleep 0.15
  ydotool click 0x80 >/dev/null
}

# Spectacles Kürzel „Bildschirm aufnehmen“ (Meta+Alt+R) über kglobalaccel. Es
# startet nicht sofort: ein Fadenkreuz wartet auf den Klick, der den Bildschirm
# wählt. Ein zweiter Aufruf beendet die Aufnahme. Die Datei landet im
# übersetzten Unterordner von Videos, in deutscher Sitzung „Bildschirmaufnahmen“.
_rec_toggle() {
  gdbus call --session -d org.kde.kglobalaccel -o /component/org_kde_spectacle_desktop \
    -m org.kde.kglobalaccel.Component.invokeShortcut RecordScreen >/dev/null
}

rec_start() {
  touch ~/hos/.rec
  _rec_toggle
  sleep 3
  click "${1:-400}" "${2:-300}"
}

rec_stop() {
  _rec_toggle
  sleep 5
  find "$(xdg-user-dir VIDEOS)" -type f -newer ~/hos/.rec \( -name '*.webm' -o -name '*.mp4' \) | sort | tail -1
}

# wl-copy ohne offene Ausgaben, sonst hält es die SSH-Sitzung offen; den Text
# als Argument, weil ein </dev/null hinter der Pipe deren Inhalt verdrängt
paste() {
  wl-copy -- "$1" >/dev/null 2>&1 </dev/null
  sleep 0.3
  ydotool key 29:1 47:1 47:0 29:0
}

frage() {
  gdbus call --session -d io.github.pottrauschen.hermesos.tray -o /runner -m org.kde.krunner1.Run "frage:$*" ""
}

frage_still() {
  gdbus call --session -d io.github.pottrauschen.hermesos.tray -o /runner -m org.kde.krunner1.Run "frage:$*" "lookup"
}
