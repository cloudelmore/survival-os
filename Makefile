.PHONY: setup test test-backend test-frontend validate build deploy check kiosk kiosk-stop

VENV := backend/.venv
PY := $(VENV)/bin/python

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -e search -e 'backend[dev]'
	cd frontend && npm ci

test: test-backend test-frontend validate

test-backend:
	$(PY) -m pytest -q tests

test-frontend:
	cd frontend && npm run typecheck && npm test

validate:
	$(PY) -m survival_os.manifests content-manifests

build:
	cd frontend && npm run build
	scripts/dev/check-offline-build.sh

deploy: build
	scripts/dev/dev-install.sh --apply
	scripts/dev/dev-check.sh

check:
	scripts/dev/dev-check.sh

kiosk:
	ssh $${SURVIVAL_HOST:-survival} sudo -n systemctl restart survival-kiosk

kiosk-stop:
	ssh $${SURVIVAL_HOST:-survival} sudo -n systemctl stop survival-kiosk
