#!/usr/bin/env bash
# hermes-os -- Image-Aufräumen, von build.sh am Ende aufgerufen.
# Muster aus querencia-linux; /var/cache/uv kommt als zweiter Cache-Mount dazu.
set -xeuo pipefail

shopt -s extglob

dnf clean all

# dnf lässt /run/dnf zurück; bootc container lint meldet das als
# nonempty-run-tmp. /run ist zur Laufzeit ohnehin ein tmpfs.
rm -rf /.gitkeep /boot /run/dnf

# /var leeren, aber die Cache-Mounts (dnf, uv) in Ruhe lassen:
# ein rm auf einen Bind-Mount scheitert mit "Device or resource busy".
find /var -mindepth 1 -maxdepth 1 -not -name 'cache' -exec rm -rf {} +
find /var/cache -mindepth 1 -maxdepth 1 -not -name 'dnf' -not -name 'uv' -exec rm -rf {} + 2>/dev/null || true

mkdir -p /boot /var

# /usr/local beschreibbar machen (Aurora macht das bereits; idempotent)
if [ ! -L /usr/local ]; then
  mv /usr/local /var/usrlocal
  ln -s /var/usrlocal /usr/local
fi
