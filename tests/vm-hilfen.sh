# shellcheck shell=bash
# =============================================================================
# hermes-os -- Hilfen, um die Plasma-Sitzung der Test-VM per SSH zu bedienen
# =============================================================================
# In die VM kopieren und in einer SSH-Sitzung einlesen:
#   sed 's/\r$//' tests/vm-hilfen.sh | ssh <user>@<vm> 'cat > ~/hosenv.sh'
#   ssh <user>@<vm>, dann:  . ~/hosenv.sh
# Das Passwort der VM kommt aus VM_PASS (nie ins Repo schreiben); nur prep
# braucht es, für sudo.
#
#   wake            Sperre aufheben, Anzeige einschalten (sonst altes oder schwarzes Bild)
#   shot [DATEI]    Bildschirmfoto der ganzen Sitzung, Vorgabe ~/hos/s.png
#   shotp [DATEI]   dasselbe mit Mauszeiger
#   prep            ydotool-Daemon starten, Zeigerbeschleunigung für ihn flach stellen
#   click X Y       Linksklick an Bildschirmkoordinaten (braucht prep)
#   paste TEXT      Text über die Zwischenablage einfügen (ydotool type kennt nur US-Belegung)
#   frage TEXT      Frage über den Runner des Leisten-Symbols ins Chat-Fenster
#   frage_still T   dasselbe ohne Fenster, Antwort als Benachrichtigung
# Beschreibung und Stolperfallen: docs/testumgebung.md, „VM 112 von hier bedienen“.
# =============================================================================

export XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 DISPLAY=:0 \
       DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus QT_QPA_PLATFORM=wayland
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

# Erst weit nach links oben, dann relativ: so ist die Position unabhängig vom Stand davor
click() {
  ydotool mousemove -x -4000 -y -4000
  sleep 0.2
  ydotool mousemove -x "$1" -y "$2"
  sleep 0.3
  ydotool click 0xC0
}

# wl-copy ohne offene Ausgaben, sonst hält es die SSH-Sitzung offen
paste() {
  printf '%s' "$1" | wl-copy >/dev/null 2>&1 </dev/null
  sleep 0.3
  ydotool key 29:1 47:1 47:0 29:0
}

frage() {
  gdbus call --session -d io.github.pottrauschen.hermesos.tray -o /runner -m org.kde.krunner1.Run "frage:$*" ""
}

frage_still() {
  gdbus call --session -d io.github.pottrauschen.hermesos.tray -o /runner -m org.kde.krunner1.Run "frage:$*" "lookup"
}
