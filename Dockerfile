# =============================================================================
# hermes-os  (Arbeitsname, siehe README)
# Atomares KDE-Linux mit Hermes Agent als Systembestandteil
# =============================================================================
# Basis: Aurora DX (Universal Blue, Fedora bootc, KDE Plasma auf Wayland).
# Aufbau nach dem Muster von querencia-linux: ein Dockerfile, das nur build.sh
# aufruft, und nummerierte Skripte in files/scripts/.
# =============================================================================

# Build-Kontext getrennt vom Image: Skripte und Systemdateien werden nur
# eingebunden, nicht ins Image kopiert.
FROM scratch AS ctx
COPY files/system /system_files/
COPY --chmod=0755 files/scripts /build_files/
COPY *.pub /keys/

# ---- Basis-Image ------------------------------------------------------------
# VARIANT=""       -> aurora-dx            (AMD / Intel)
# VARIANT="nvidia" -> aurora-dx-nvidia-open (NVIDIA, offener Kernel-Modul)
ARG VARIANT=""
ARG BASE_TAG="stable"
ARG BASE_IMAGE="ghcr.io/ublue-os/aurora-dx${VARIANT:+-${VARIANT}-open}"
FROM ${BASE_IMAGE}:${BASE_TAG}

ARG IMAGE_NAME="hermes-os"
ARG IMAGE_REGISTRY="localhost"
ARG VARIANT=""
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
LABEL org.opencontainers.image.version="0.1"
LABEL ostree.bootable="true"

RUN --mount=type=cache,dst=/var/cache/dnf \
    --mount=type=cache,dst=/var/cache/uv \
    --mount=type=tmpfs,dst=/tmp \
    --mount=type=bind,from=ctx,source=/,target=/ctx \
    /ctx/build_files/build.sh

RUN bootc container lint
