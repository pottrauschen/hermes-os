#!/usr/bin/env bash
# =============================================================================
# hermes-os -- Ollama als Systembestandteil (lokales Modell ohne Cloud)
# =============================================================================
# Legt Ollama aus dem gepinnten Release-Tarball nach /usr/bin/ollama und
# /usr/lib/ollama, mit SHA256-Prüfung wie uv in 10-hermes.sh. Warum nativ und
# nicht als Podman-Quadlet, und warum Ollama statt llama-server, steht in
# docs/lokales-modell.md. Kurz: Ollama sucht seine Rechen-Backends zur
# Laufzeit selbst (CUDA über den NVIDIA-Treiber, Vulkan über Mesa oder den
# NVIDIA-Treiber, sonst CPU); deshalb ist dieser Schritt in beiden
# Dockerfiles identisch, und nichts hier fragt zur Bauzeit nach der GPU.
#
# Das Archiv (rund 1,3 GB) enthält:
#   bin/ollama, lib/ollama/  CPU-Backends je Prozessorfamilie, llama-server
#   lib/ollama/cuda_v12      CUDA 12.8 mit cuBLAS, 1,3 GB, für Treiber vor 580
#   lib/ollama/cuda_v13      CUDA 13.0 mit cuBLAS, 0,85 GB, Treiber ab 580
#   lib/ollama/vulkan        43 MB, AMD/Intel über Mesa, NVIDIA als Ausweich
# cuda_v12 fliegt raus: aurora-dx-nvidia-open bringt den aktuellen Treiber
# (615.71.09 am 2026-09-26) und die offenen Kernelmodule laufen erst ab
# Turing, das ist genau die Klasse, die cuda_v13 abdeckt. Spart 1,3 GB in
# beiden Images.
#
# Ein Bump ist eine Änderung von OLLAMA_PIN hier; vorher in Test-VM 112
# `ujust hermes-lokal-ein` und `ollama ps` (100 % GPU) prüfen.
# =============================================================================
set -xeuo pipefail

OLLAMA_PIN="${OLLAMA_PIN:-0.34.4}"
OLLAMA_ASSET="ollama-linux-amd64.tar.zst"
OLLAMA_BASE="https://github.com/ollama/ollama/releases/download/v${OLLAMA_PIN}"

# tar braucht zstd für das Archiv; Aurora hat libzstd, aber nicht immer das
# Werkzeug. PyYAML für den Helfer hermes-os-lokal und First-Login (Fedoras
# Python); ist meist schon da, dann ein No-op.
dnf install -y zstd python3-pyyaml

WORK=/tmp/ollama-bootstrap
rm -rf "${WORK}"
mkdir -p "${WORK}"
cd "${WORK}"
curl -fsSL --retry 3 -o "${OLLAMA_ASSET}" "${OLLAMA_BASE}/${OLLAMA_ASSET}"
curl -fsSL --retry 3 -o sha256sum.txt "${OLLAMA_BASE}/sha256sum.txt"
# Zeilenformat der sha256sum.txt: "<64 hex>  ./<datei>" in beliebiger
# Reihenfolge (find | xargs sha256sum im Release-Workflow). Genau die Zeile
# unseres Archivs nehmen; "-rocm" und "-mlx" enden anders.
SUM_LINE="$(grep -E "^[0-9a-f]{64}  \./${OLLAMA_ASSET}\$" sha256sum.txt)"
[ "$(printf '%s\n' "${SUM_LINE}" | wc -l)" -eq 1 ]
echo "${SUM_LINE%% *}  ${OLLAMA_ASSET}" | sha256sum -c -

mkdir -p extract
tar --zstd -xf "${OLLAMA_ASSET}" -C extract
# Das Archiv ist zum Entpacken nach /usr gedacht (bin/, lib/); falls ein
# Release doch usr/ voranstellt, beide Formen annehmen.
ROOT=extract
[ -d "${ROOT}/usr/lib/ollama" ] && ROOT=extract/usr
[ -x "${ROOT}/bin/ollama" ] && [ -d "${ROOT}/lib/ollama" ]

rm -rf "${ROOT}/lib/ollama/cuda_v12"
rm -rf /usr/lib/ollama
install -m0755 "${ROOT}/bin/ollama" /usr/bin/ollama
cp -a "${ROOT}/lib/ollama" /usr/lib/ollama
chmod -R u=rwX,go=rX /usr/lib/ollama

# Backends, die Ollama zur Laufzeit vorfindet; das Gate und os_status lesen
# den Stempel.
BACKENDS="$(cd /usr/lib/ollama && ls -d cuda_v* vulkan rocm* 2>/dev/null | tr '\n' ' ' | sed 's/ $//')"
cat > /usr/lib/ollama/.hermes-os-release <<STAMP
version=${OLLAMA_PIN}
asset=${OLLAMA_ASSET}
sha256=${SUM_LINE%% *}
backends=cpu ${BACKENDS}
update=image
STAMP

# Läuft das Binary? (Warnung "could not connect" ist normal, kein Server.)
/usr/bin/ollama --version
du -sh /usr/lib/ollama
cd /
rm -rf "${WORK}"
