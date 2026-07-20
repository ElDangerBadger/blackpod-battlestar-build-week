SHELL := /bin/sh
.DEFAULT_GOAL := help

BOOTSTRAP_PYTHON ?= python3.11
VENV ?= .venv
PYTHON ?= $(VENV)/bin/python3.11
DEMO_ROOT ?= artifacts/demo-readiness

# REPLAY still validates the strict local ModelDock configuration, but never
# opens a network connection.  MODELDOCK_MODEL is deliberately removed so an
# inherited LIVE model selection cannot conflict with the committed replay pack.
MODELDOCK_BASE_URL ?= http://127.0.0.1:8000
MODELDOCK_TIMEOUT_SECONDS ?= 30
MODELDOCK_PROFILE ?= default
MODELDOCK_PROVIDER ?= mlx

CLI := $(PYTHON) -m blackpod_build_week.harbormaster
REPLAY_ENV := env -u MODELDOCK_MODEL \
	BATTLESTAR_PATH="$(BATTLESTAR_PATH)" \
	MODELDOCK_BASE_URL="$(MODELDOCK_BASE_URL)" \
	MODELDOCK_TIMEOUT_SECONDS="$(MODELDOCK_TIMEOUT_SECONDS)" \
	MODELDOCK_PROFILE="$(MODELDOCK_PROFILE)" \
	MODELDOCK_PROVIDER="$(MODELDOCK_PROVIDER)"

.PHONY: help setup test require-battlestar preflight-replay \
	validate-demo-packs demo demo-approved demo-held demo-vetoed demo-failed \
	demo-incomplete demo-outcomes rehearse-approved

help:
	@echo "BlackPod Battlestar Build Week demo targets"
	@echo
	@echo "  make setup                 Create .venv and install the package"
	@echo "  make test                  Run the complete offline test suite"
	@echo "  make preflight-replay      Validate replay demo readiness"
	@echo "  make validate-demo-packs   Validate every committed demo pack"
	@echo "  make demo                  Run the canonical APPROVED replay"
	@echo "  make demo-outcomes         Run all five canonical outcomes"
	@echo "  make rehearse-approved     Validate, run, and inspect APPROVED"
	@echo
	@echo "Set BATTLESTAR_PATH to the read-only Battlestar checkout first."
	@echo "Override DEMO_ROOT for a fresh isolated rehearsal."

setup:
	$(BOOTSTRAP_PYTHON) -m venv "$(VENV)"
	$(PYTHON) -m pip install -e .

test:
	$(PYTHON) -m unittest discover -s tests -v

require-battlestar:
	@if [ -z "$(strip $(BATTLESTAR_PATH))" ]; then \
		echo "BATTLESTAR_PATH is required; point it at the read-only Battlestar checkout." >&2; \
		exit 2; \
	fi
	@if [ ! -d "$(BATTLESTAR_PATH)" ]; then \
		echo "BATTLESTAR_PATH is not a directory: $(BATTLESTAR_PATH)" >&2; \
		exit 2; \
	fi

preflight-replay: require-battlestar
	$(REPLAY_ENV) $(CLI) preflight --mode replay --artifacts-root "$(DEMO_ROOT)/preflight"

validate-demo-packs: require-battlestar
	$(REPLAY_ENV) $(CLI) validate-demo-packs --artifacts-root "$(DEMO_ROOT)/validation"

demo: demo-approved

demo-approved: require-battlestar
	$(REPLAY_ENV) $(CLI) demo approved --artifacts-root "$(DEMO_ROOT)/approved"

demo-held: require-battlestar
	$(REPLAY_ENV) $(CLI) demo held --artifacts-root "$(DEMO_ROOT)/held"

demo-vetoed: require-battlestar
	$(REPLAY_ENV) $(CLI) demo vetoed --artifacts-root "$(DEMO_ROOT)/vetoed"

demo-failed: require-battlestar
	@set +e; \
	$(REPLAY_ENV) $(CLI) demo failed --artifacts-root "$(DEMO_ROOT)/failed"; \
	status=$$?; \
	set -e; \
	if [ $$status -ne 11 ]; then \
		echo "Expected the controlled FAILED scenario to exit 11; received $$status." >&2; \
		if [ $$status -eq 0 ]; then exit 1; else exit $$status; fi; \
	fi; \
	echo "Controlled FAILED scenario produced the expected exit code 11."

demo-incomplete: require-battlestar
	$(REPLAY_ENV) $(CLI) demo incomplete --artifacts-root "$(DEMO_ROOT)/incomplete"

demo-outcomes: demo-approved demo-held demo-vetoed demo-failed demo-incomplete

rehearse-approved: require-battlestar
	$(REPLAY_ENV) $(CLI) demo approved --rehearse --artifacts-root "$(DEMO_ROOT)/approved-rehearsal"
