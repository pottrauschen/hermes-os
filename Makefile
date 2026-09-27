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
	shellcheck -x files/scripts/*.sh files/system/usr/libexec/hermes-os-first-login tests/*.sh || true
	python3 -c 'import ast,sys; [ast.parse(open(f, encoding="utf-8").read(), f) for f in sys.argv[1:]]; print("python syntax ok")' \
		files/system/usr/share/hermes-os/plugins/hermes_os/*.py \
		files/system/usr/share/hermes-os/setup/hermes_bridge.py files/system/usr/libexec/hermes-os-setup \
		files/system/usr/share/hermes-os/tray/hermes_client.py files/system/usr/libexec/hermes-os-tray \
		files/system/usr/libexec/hermes-os-morgenbericht \
		files/system/usr/share/hermes-os/tray/runner.py files/system/usr/share/hermes-os/tray/dbus_peer.py \
		files/system/usr/share/hermes-os/dashboard/dashboard_server.py files/system/usr/libexec/hermes-os-dashboard \
		files/system/usr/libexec/hermes-os-lokal files/system/usr/share/hermes-os/local/local_model.py \
		tests/*.py
	python3 files/system/usr/share/hermes-os/tray/hermes_client.py
	python3 tests/tray-client-check.py --tray-dir files/system/usr/share/hermes-os/tray
	python3 tests/library-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
	python3 tests/library2-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os --config-template files/system/usr/share/hermes-os/config.yaml.default
	python3 tests/boundary-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
	python3 tests/audit-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
	python3 tests/report-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
	python3 tests/runner-check.py --tray-dir files/system/usr/share/hermes-os/tray
	python3 tests/dashboard-check.py --dashboard-dir files/system/usr/share/hermes-os/dashboard \
		--launcher files/system/usr/libexec/hermes-os-dashboard \
		--desktop-file files/system/usr/share/applications/hermes-os-dashboard.desktop
	python3 tests/lokales-modell-check.py --local-dir files/system/usr/share/hermes-os/local
	@diff <(grep -vE '^FROM ghcr.io/ublue-os/' Dockerfile) <(grep -vE '^FROM ghcr.io/ublue-os/' Dockerfile.nvidia) \
		&& echo "Dockerfile.nvidia differs only in the base FROM line" \
		|| { echo "Dockerfile and Dockerfile.nvidia have drifted apart"; exit 1; }
	@# Die CI liest die Aurora-Zeile mit `grep '^FROM ghcr.io/ublue-os/' | tail -1`;
	@# die Node-Stufe des Dashboards steht davor, die letzte FROM-Zeile muss
	@# die Aurora-Basis bleiben, und es darf nur eine geben.
	@for f in Dockerfile Dockerfile.nvidia; do \
		grep -E '^FROM ' "$$f" | tail -1 | grep -qE '^FROM ghcr.io/ublue-os/' \
			|| { echo "$$f: last FROM line is not the Aurora base"; exit 1; }; \
		[ "$$(grep -cE '^FROM ghcr.io/ublue-os/' "$$f")" = "1" ] \
			|| { echo "$$f: expected exactly one Aurora FROM line"; exit 1; }; \
	done; echo "Aurora base is the final stage in both Dockerfiles"
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
