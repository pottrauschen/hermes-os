#!/bin/bash
# hermes-os -- Build-Einstieg (vom Dockerfile aufgerufen)
# Kopiert files/system nach /, führt dann alle NN-*.sh in Reihenfolge aus
# und räumt am Ende auf. Unverändertes Muster aus querencia-linux.

set -ouex pipefail

CONTEXT_PATH="$(realpath "$(dirname "$0")/..")"   # /ctx
BUILD_SCRIPTS_PATH="$(realpath "$(dirname "$0")")" # /ctx/build_files

printf "::group:: === Copying files ===\n"
cp -avf "${CONTEXT_PATH}/system_files/." /
printf "::endgroup::\n"

for script in $(find "${BUILD_SCRIPTS_PATH}" -maxdepth 1 -iname "*-*.sh" -type f | sort --sort=human-numeric); do
  printf "::group:: === %s ===\n" "$(basename "$script")"
  "$(realpath "$script")"
  printf "::endgroup::\n"
done

printf "::group:: === Image Cleanup ===\n"
"${BUILD_SCRIPTS_PATH}/cleanup.sh"
printf "::endgroup::\n"
