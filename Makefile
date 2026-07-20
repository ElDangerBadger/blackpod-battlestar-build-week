SHELL := /bin/sh
.DEFAULT_GOAL := help

BOOTSTRAP_PYTHON ?= python3.11
VENV ?= .venv
PYTHON ?= $(VENV)/bin/python3.11
DEMO_ROOT ?= artifacts/demo-readiness
JUDGE_ROOT ?= $(DEMO_ROOT)/judge
JUDGE_MISSION_ID := mission-buildweek-replay-001
UI_DIR ?= ui
NPM ?= npm
CABIN_SOURCE ?= $(JUDGE_ROOT)/approved/missions/$(JUDGE_MISSION_ID)
CABIN_DEMO_ROOT ?= $(UI_DIR)/public/demo/approved

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

.PHONY: help setup test require-battlestar preflight-replay judge \
	validate-demo-packs demo demo-approved demo-held demo-vetoed demo-failed \
	demo-incomplete demo-outcomes rehearse-approved cabin-prepare cabin-dev \
	cabin-build cabin-test

help:
	@echo "BlackPod Battlestar Build Week demo targets"
	@echo
	@echo "  make setup                 Create .venv and install the package"
	@echo "  make test                  Run the complete offline test suite"
	@echo "  make preflight-replay      Validate replay demo readiness"
	@echo "  make judge                 Run the judge-ready APPROVED replay and brief"
	@echo "  make validate-demo-packs   Validate every committed demo pack"
	@echo "  make demo                  Run the canonical APPROVED replay"
	@echo "  make demo-outcomes         Run all five canonical outcomes"
	@echo "  make rehearse-approved     Validate, run, and inspect APPROVED"
	@echo "  make cabin-prepare         Materialize the approved mission for the cabin"
	@echo "  make cabin-dev             Prepare and launch the Captain's Cabin"
	@echo "  make cabin-build           Prepare and build the Captain's Cabin"
	@echo "  make cabin-test            Run the focused Captain's Cabin tests"
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

judge: require-battlestar
	$(REPLAY_ENV) $(CLI) preflight --mode replay --artifacts-root "$(JUDGE_ROOT)/preflight"
	$(REPLAY_ENV) $(CLI) demo approved --no-color --artifacts-root "$(JUDGE_ROOT)/approved"
	test -f "$(JUDGE_ROOT)/approved/missions/$(JUDGE_MISSION_ID)/presentation/mission_brief.html"
	@echo
	@echo "Judge mission brief:"
	@echo "$(JUDGE_ROOT)/approved/missions/$(JUDGE_MISSION_ID)/presentation/mission_brief.html"

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

cabin-prepare: judge
	$(PYTHON) scripts/prepare_cabin_demo.py \
		--source "$(CABIN_SOURCE)" \
		--destination "$(CABIN_DEMO_ROOT)"

cabin-dev: cabin-prepare
	$(NPM) --prefix "$(UI_DIR)" run dev

cabin-build: cabin-prepare
	$(NPM) --prefix "$(UI_DIR)" run build

cabin-test:
	$(NPM) --prefix "$(UI_DIR)" run test
