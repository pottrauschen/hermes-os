# hermes-os -- lokale Builds (Podman auf Linux). Muster aus querencia-linux.
SUDO = sudo
PODMAN = $(SUDO) podman

IMAGE_NAME ?= localhost/hermes-os
CONTAINER_FILE ?= ./Dockerfile
VARIANT ?=
HERMES_REF ?= v2026.9.24
IMAGE_CONFIG ?= ./iso.toml

IMAGE_TYPE ?= qcow2
QEMU_DISK_QCOW2 ?= ./output/qcow2/disk.qcow2
QEMU_ISO ?= ./output/bootiso/install.iso

SHELL := /bin/bash
.PHONY: clean image bib_image iso qcow2 run-qemu-qcow run-qemu-iso lint

.ONESHELL:

clean:
	$(SUDO) rm -rf ./output

# Syntaxprüfung ohne Build (shellcheck + python -m py_compile), läuft überall.
lint:
	shellcheck -x files/scripts/*.sh files/system/usr/libexec/hermes-os-first-login || true
	python3 -m py_compile files/system/usr/share/hermes-os/plugins/hermes_os/*.py
	@echo "lint ok"

image:
	$(PODMAN) build \
		--security-opt=label=disable \
		--cap-add=all \
		--device /dev/fuse \
		--build-arg IMAGE_NAME=hermes-os \
		--build-arg IMAGE_REGISTRY=localhost \
		--build-arg VARIANT=$(VARIANT) \
		--build-arg HERMES_REF=$(HERMES_REF) \
		-t $(IMAGE_NAME) \
		-f $(CONTAINER_FILE) \
		.

bib_image:
	$(SUDO) rm -rf ./output
	mkdir -p ./output
	cp $(IMAGE_CONFIG) ./output/config.toml
	if [ "$(IMAGE_TYPE)" = "iso" ]; then LIBREPO=False; else LIBREPO=True; fi
	$(PODMAN) run --rm -it --privileged --pull=newer \
		--security-opt label=type:unconfined_t \
		-v ./output:/output \
		-v ./output/config.toml:/config.toml:ro \
		-v /var/lib/containers/storage:/var/lib/containers/storage \
		quay.io/centos-bootc/bootc-image-builder:latest \
		--type $(IMAGE_TYPE) --use-librepo=$$LIBREPO --progress verbose \
		$(IMAGE_NAME)

iso:
	make bib_image IMAGE_TYPE=iso

qcow2:
	make bib_image IMAGE_TYPE=qcow2

run-qemu-qcow:
	qemu-system-x86_64 -M accel=kvm -cpu host -smp 4 -m 8192 \
		-bios /usr/share/OVMF/x64/OVMF.4m.fd -serial stdio \
		-snapshot $(QEMU_DISK_QCOW2)

run-qemu-iso:
	mkdir -p ./output
	[[ ! -e ./output/disk.raw ]] && dd if=/dev/null of=./output/disk.raw bs=1M seek=40960
	qemu-system-x86_64 -M accel=kvm -cpu host -smp 4 -m 8192 \
		-bios /usr/share/OVMF/x64/OVMF.4m.fd -serial stdio \
		-boot d -cdrom $(QEMU_ISO) -hda ./output/disk.raw
