# =============================================================================
# hermes-os  (Arbeitsname, siehe README)
# Atomares KDE-Linux mit Hermes Agent als Systembestandteil
# =============================================================================
# Basis: Aurora DX (Universal Blue, Fedora bootc, KDE Plasma auf Wayland).
# Aufbau nach dem Muster von querencia-linux: ein Dockerfile, das nur build.sh
# aufruft, und nummerierte Skripte in files/scripts/.
#
# Die FROM-Zeile MUSS literal sein: der CI-Workflow liest sie mit grep, prüft
# die Signatur des Basis-Images gegen aurora-cosign.pub und leitet die
# Image-Version daraus ab. Die NVIDIA-Variante ist deshalb eine eigene Datei
# (Dockerfile.nvidia), die sich nur in dieser Zeile unterscheidet; `make lint`
# prüft das.
# =============================================================================

# Build-Kontext getrennt vom Image: Skripte und Systemdateien werden nur
# eingebunden, nicht ins Image kopiert.
FROM scratch AS ctx
COPY files/system /system_files/
COPY --chmod=0755 files/scripts /build_files/
COPY *.pub /keys/
# Tests aus dem Repo, die das Validierungs-Gate im Build ausführt (Render-Test
# des Einrichtungsassistenten); bleiben im Kontext, landen nicht im Image.
COPY tests /tests/

FROM ghcr.io/ublue-os/aurora-dx:stable

ARG IMAGE_NAME="hermes-os"
ARG IMAGE_REGISTRY="localhost"
ARG VARIANT=""
# Version des Images: die CI setzt <Aurora-Version>.<Datum>, lokal bleibt es
# ein Platzhalter. Ohne eigenen Wert erbt das Label die Aurora-Version.
ARG IMAGE_VERSION="0.1"
# Hermes-Release, das ins Image gebacken wird. Ein Bump ist ein Commit hier,
# kein `hermes update` auf dem Rechner (das ist auf dem read-only /usr
# absichtlich nicht möglich).
#
# Die Tags v2026.x.y liegen auf der Release-Linie 0.21.x (Python 3.11-3.13).
# main ist bereits bei Python 3.14 und einem anderen Build-System; wer main
# pinnen will, muss HERMES_PYTHON mit anheben und 10-hermes.sh prüfen.
ARG HERMES_REF="v2026.9.24"
ARG HERMES_PYTHON="3.13"
ARG HERMES_REPO="https://github.com/NousResearch/hermes-agent.git"

ENV VARIANT=${VARIANT}
ENV IMAGE_NAME=${IMAGE_NAME}
ENV IMAGE_REGISTRY=${IMAGE_REGISTRY}
ENV HERMES_REF=${HERMES_REF}
ENV HERMES_PYTHON=${HERMES_PYTHON}
ENV HERMES_REPO=${HERMES_REPO}

LABEL org.opencontainers.image.title="hermes-os"
LABEL org.opencontainers.image.description="Atomic KDE desktop with Hermes Agent as a system component (Aurora DX base)"
LABEL org.opencontainers.image.vendor="pottrauschen"
LABEL org.opencontainers.image.version="${IMAGE_VERSION}"
LABEL ostree.bootable="true"

# Cache-Mounts: dnf5 auf Fedora cacht unter /var/cache/libdnf5 (nicht
# /var/cache/dnf wie dnf4 auf AlmaLinux). Beide Mountpunkte sind in
# usr/lib/tmpfiles.d/hermes-os.conf deklariert, damit bootc container lint
# nicht über undeklarierten Inhalt unter /var stolpert.
RUN --mount=type=cache,dst=/var/cache/libdnf5 \
    --mount=type=cache,dst=/var/cache/uv \
    --mount=type=tmpfs,dst=/tmp \
    --mount=type=bind,from=ctx,source=/,target=/ctx \
    /ctx/build_files/build.sh

RUN bootc container lint
