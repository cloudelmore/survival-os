.PHONY: setup test test-backend test-frontend validate build deploy check kiosk kiosk-stop

VENV := backend/.venv
PY := $(VENV)/bin/python

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -e 'backend[dev]'
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
	scripts/dev/dev-deploy.sh

check:
	scripts/dev/dev-check.sh

kiosk:
	scripts/dev/dev-kiosk.sh start

kiosk-stop:
	scripts/dev/dev-kiosk.sh stop
