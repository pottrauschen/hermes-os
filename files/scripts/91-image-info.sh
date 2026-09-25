#!/usr/bin/env bash

# DO NOT MODIFY THIS FILE UNLESS YOU KNOW WHAT YOU ARE DOING
# (unverändert aus dem AlmaLinux Atomic Respin Template via querencia-linux)

set -xeuo pipefail

# Remove current VARIANT_ID, if it exists.
sed -i '/VARIANT_ID=/d;' /usr/lib/os-release

# Add our image name as VARIANT_ID.
echo "VARIANT_ID=\"${IMAGE_NAME}\"" >> /usr/lib/os-release
