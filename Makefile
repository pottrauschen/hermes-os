# hermes-os -- lokale Builds (Podman auf Linux). Muster aus querencia-linux.
SUDO = sudo
PODMAN = $(SUDO) podman

IMAGE_NAME ?= localhost/hermes-os
VARIANT ?=
# VARIANT=nvidia wählt Dockerfile.nvidia (literale FROM-Zeile, siehe Dockerfile-Kopf)
CONTAINER_FILE ?= $(if $(VARIANT),./Dockerfile.$(VARIANT),./Dockerfile)
HERMES_REF ?= v2026.9.24
HERMES_PYTHON ?= 3.13
IMAGE_TYPE ?= qcow2
# Konfiguration je Ausgabetyp: die ISO bekommt den Anaconda-Installer aus
# iso.toml, ein Datenträger (qcow2, raw) einen Nutzer aus disk.toml. Liegt eine
# disk.local.toml daneben (in .gitignore), gewinnt sie: dort stehen Passwort und
# SSH-Schlüssel für Test-VMs, die nicht ins Repo gehören.
IMAGE_CONFIG ?= $(if $(filter iso,$(IMAGE_TYPE)),./iso.toml,$(if $(wildcard disk.local.toml),./disk.local.toml,./disk.toml))
# Wurzeldateisystem des Datenträgers. Aurora deklariert btrfs selbst
# (/usr/lib/bootc/install/20-aurora.toml); das Flag hält die Wahl sichtbar und
# deckt Basis-Images ohne Vorgabe ab, bei denen der Builder sonst mit "missing
# required info: DefaultRootFs" abbricht (ublue base-main).
ROOTFS ?= btrfs
QEMU_DISK_QCOW2 ?= ./output/qcow2/disk.qcow2
QEMU_ISO ?= ./output/bootiso/install.iso

SHELL := /bin/bash
.PHONY: clean image bib_image iso qcow2 run-qemu-qcow run-qemu-iso lint

.ONESHELL:

clean:
	$(SUDO) rm -rf ./output

# Syntaxprüfung ohne Build (shellcheck + python -m py_compile), läuft überall.
# Prüft außerdem, dass Dockerfile und Dockerfile.nvidia nur in der FROM-Zeile
# des Basis-Images abweichen.
lint:
	shellcheck -x files/scripts/*.sh files/system/usr/libexec/hermes-os-first-login || true
	python3 -c 'import ast,sys; [ast.parse(open(f).read(), f) for f in sys.argv[1:]]; print("python syntax ok")' files/system/usr/share/hermes-os/plugins/hermes_os/*.py
	@diff <(grep -vE '^FROM ghcr.io/ublue-os/' Dockerfile) <(grep -vE '^FROM ghcr.io/ublue-os/' Dockerfile.nvidia) \
		&& echo "Dockerfile.nvidia differs only in the base FROM line" \
		|| { echo "Dockerfile and Dockerfile.nvidia have drifted apart"; exit 1; }
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
		--build-arg HERMES_PYTHON=$(HERMES_PYTHON) \
		-t $(IMAGE_NAME) \
		-f $(CONTAINER_FILE) \
		.

bib_image:
	$(SUDO) rm -rf ./output
	mkdir -p ./output
	cp $(IMAGE_CONFIG) ./output/config.toml
	@echo "Konfiguration: $(IMAGE_CONFIG)"
	# Kennung des Images nennen, aus dem der Datenträger entsteht: der Builder
	# liest den root-Speicher und nähme sonst wortlos einen älteren Stand.
	$(PODMAN) image inspect $(IMAGE_NAME) --format "Datentraeger aus {{.Id}} (erstellt {{.Created}})"
	if [ "$(IMAGE_TYPE)" = "iso" ]; then LIBREPO=False; EXTRA=""; else LIBREPO=True; EXTRA="--rootfs $(ROOTFS)"; fi
	$(PODMAN) run --rm -it --privileged --pull=newer \
		--security-opt label=type:unconfined_t \
		-v ./output:/output \
		-v ./output/config.toml:/config.toml:ro \
		-v /var/lib/containers/storage:/var/lib/containers/storage \
		quay.io/centos-bootc/bootc-image-builder:latest \
		--type $(IMAGE_TYPE) $$EXTRA --use-librepo=$$LIBREPO --progress verbose \
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
