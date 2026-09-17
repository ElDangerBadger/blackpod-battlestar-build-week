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
CABIN_ARTIFACTS_ROOT ?=
CABIN_MISSION_ID ?=
CABIN_LIVE_PORT ?= 5174
NAVIGATOR_LIVE_URL ?=
NAVIGATOR_LIVE_PORT ?= 8001
ALPACA_DATA_FEED ?= iex
SENTRY_ARCHIVE ?=
SENTRY_SOURCE_KIND ?=
SENTRY_SOURCE_LABEL ?=
SENTRY_CANONICAL_ROOT ?=
CABIN_READER := $(PYTHON) -m blackpod_build_week.cabin_reader
CABIN_READER_ARGS = --ui-root "$(UI_DIR)/dist" --port "$(CABIN_LIVE_PORT)" \
	$(if $(strip $(CABIN_ARTIFACTS_ROOT)),--artifacts-root "$(CABIN_ARTIFACTS_ROOT)",) \
	$(if $(strip $(CABIN_MISSION_ID)),--mission-id "$(CABIN_MISSION_ID)",)

ifneq ($(strip $(NAVIGATOR_LIVE_URL)),)
CABIN_READER_ARGS += --navigator-live-url "$(NAVIGATOR_LIVE_URL)"
endif
ifneq ($(strip $(SENTRY_ARCHIVE)$(SENTRY_SOURCE_KIND)$(SENTRY_SOURCE_LABEL)$(SENTRY_CANONICAL_ROOT)),)
CABIN_READER_ARGS += --sentry-archive "$(SENTRY_ARCHIVE)" --sentry-source-kind "$(SENTRY_SOURCE_KIND)" \
	--sentry-source-label "$(SENTRY_SOURCE_LABEL)" --sentry-canonical-root "$(SENTRY_CANONICAL_ROOT)"
endif
CABIN_SOURCE ?= $(JUDGE_ROOT)/approved/missions/$(JUDGE_MISSION_ID)
CABIN_DEMO_SOURCE ?= $(CABIN_SOURCE)
CABIN_DEMO_ROOT ?= $(UI_DIR)/public/demo/approved
CABIN_LIVE_ROOT ?= $(UI_DIR)/public/demo/live
CABIN_DEMO_MARKET_FIXTURE ?= fixtures/cabin/aapl_navigator_market.live_capture.json
CABIN_DEMO_NAVIGATOR_REVISION ?= 4a53229ad81627267f5d819775cb5df2ce8cf017
CABIN_DEMO_MARKET_SOURCE_IDENTITY ?= navigator-api-aapl-live-capture-2026-07-17
CABIN_DEMO_CAPTURED_AT ?= 2026-07-20T06:20:00Z

# Stage 4 LIVE is deliberately explicit.  The request and policy/context files
# are operator-selected inputs; Make never manufactures them or falls back to a
# replay fixture.  LIVE_MISSION_ID must match the mission_id in LIVE_REQUEST.
LIVE_ARTIFACTS_ROOT ?= artifacts/stage4-live
LIVE_REQUEST ?=
LIVE_MISSION_ID ?=
LIVE_COUNCIL_POLICY ?=
LIVE_GOVERNOR_CONTEXT ?=
LIVE_OPERATOR_ID ?= build-week-operator
LIVE_OPERATOR_REASON ?= Approved for Navigator SHADOW planning only.
LIVE_EXPIRES_MINUTES ?= 60
LIVE_DEADLINE_SECONDS ?= 300
LIVE_MODELDOCK_TIMEOUT_SECONDS ?= 300
MODELDOCK_MODEL ?=

# Optional, read-only Captain's Cabin context.  Exactly one market source and
# one Navigator revision source are required by cabin-capture-live.  A
# portfolio JSON file is accepted only when supplied explicitly.
NAVIGATOR_MARKET_URL ?=
NAVIGATOR_MARKET_JSON ?=
NAVIGATOR_REVISION ?=
NAVIGATOR_REPOSITORY ?=
NAVIGATOR_MARKET_SOURCE_IDENTITY ?= navigator-local-json
PORTFOLIO_JSON ?=
CABIN_CAPTURED_AT ?=

BUILD_WEEK_ROOT := $(CURDIR)
CABIN_LIVE_SOURCE = $(LIVE_ARTIFACTS_ROOT)/missions/$(LIVE_MISSION_ID)

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
LIVE_ENV := env \
	BATTLESTAR_PATH="$(BATTLESTAR_PATH)" \
	MODELDOCK_BASE_URL="$(MODELDOCK_BASE_URL)" \
	MODELDOCK_TIMEOUT_SECONDS="$(LIVE_MODELDOCK_TIMEOUT_SECONDS)" \
	MODELDOCK_PROFILE="$(MODELDOCK_PROFILE)" \
	MODELDOCK_PROVIDER="$(MODELDOCK_PROVIDER)" \
	MODELDOCK_MODEL="$(MODELDOCK_MODEL)"

CABIN_MARKET_ARGUMENT = $(if $(strip $(NAVIGATOR_MARKET_URL)),--market-url "$(NAVIGATOR_MARKET_URL)",--market-json "$(NAVIGATOR_MARKET_JSON)")
CABIN_NAVIGATOR_REVISION_ARGUMENT = $(if $(strip $(NAVIGATOR_REVISION)),--navigator-revision "$(NAVIGATOR_REVISION)",--navigator-repository "$(NAVIGATOR_REPOSITORY)")
CABIN_PORTFOLIO_ARGUMENT = $(if $(strip $(PORTFOLIO_JSON)),--portfolio-json "$(PORTFOLIO_JSON)",)

.PHONY: help setup test require-battlestar require-modeldock-live \
	require-live-mission-inputs require-live-mission require-cabin-context-inputs \
	preflight-replay preflight-live live-mission package-live-demo judge \
	validate-demo-packs demo demo-approved demo-held demo-vetoed demo-failed \
	demo-incomplete demo-outcomes rehearse-approved cabin-prepare cabin-dev \
	cabin-build cabin-test cabin-capture-demo cabin-capture-live cabin-prepare-demo \
	cabin-prepare-live cabin-freeze-live-demo cabin-dev-demo cabin-dev-live \
	cabin-build-demo cabin-build-live cabin-e2e navigator-check navigator-check-upstream \
	cabin-live cabin-reader cabin-build-replay cabin-dev-replay navigator-live

help:
	@echo "BlackPod Battlestar — live read-only Captain's Cabin"
	@echo "  make cabin-live            Build and serve on 127.0.0.1:5174 (no mission execution)"
	@echo "    CABIN_ARTIFACTS_ROOT=/path/to/artifacts CABIN_MISSION_ID=mission-id"
	@echo "  make cabin-reader          Start the read-only reader without rebuilding"
	@echo "  make navigator-live        Start canonical Alpaca market-data streaming (BATTLESTAR_PATH required)"
	@echo "    Add NAVIGATOR_LIVE_URL=http://127.0.0.1:8001 to cabin-live/cabin-reader"
	@echo "  Optional Sentry archive: SENTRY_ARCHIVE, SENTRY_SOURCE_KIND, SENTRY_SOURCE_LABEL, SENTRY_CANONICAL_ROOT"
	@echo "  make cabin-dev             Start Vite; proxies /live to the reader on port 5174"
	@echo "  make cabin-build           Build product assets only; no replay data"
	@echo "  make cabin-build-replay    Explicit historical regression build (includes fixtures)"
	@echo "  make cabin-dev-replay      Prepare historical fixtures; open /?mode=replay"
	@echo "Historical developer/operator targets below are NOT product startup:"
	@echo
	@echo "  make setup                 Create .venv and install the package"
	@echo "  make test                  Run the complete offline test suite"
	@echo "  make preflight-replay      Validate replay demo readiness"
	@echo "  make preflight-live        Validate real local LIVE readiness"
	@echo "  make live-mission          Run one explicit LIVE mission (no fallback)"
	@echo "  make package-live-demo     Validate/freeze an APPROVED LIVE mission"
	@echo "  make judge                 Run the judge-ready APPROVED replay and brief"
	@echo "  make validate-demo-packs   Validate every committed demo pack"
	@echo "  make demo                  Run the canonical APPROVED replay"
	@echo "  make demo-outcomes         Run all five canonical outcomes"
	@echo "  make rehearse-approved     Validate, run, and inspect APPROVED"
	@echo "  make cabin-prepare         Materialize the approved mission for the cabin"
	@echo "  make cabin-capture-demo    Attach the frozen AAPL chart context offline"
	@echo "  make cabin-prepare-live    Materialize a verified LIVE mission as Live"
	@echo "  make cabin-freeze-live-demo  Materialize verified LIVE evidence as Demo"
	@echo "  make cabin-capture-live    Capture read-only Navigator/portfolio context"
	@echo "  make cabin-test            Run the focused Captain's Cabin tests"
	@echo "  make cabin-e2e             Build and browser-test the prepared Cabin data"
	@echo "  make navigator-check       Check the reviewed renderer snapshot locally"
	@echo "  make navigator-check-upstream  Also compare canonical Battlestar sources"
	@echo
	@echo "Historical orchestration targets require BATTLESTAR_PATH; the reader does not."
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

require-modeldock-live:
	@if [ -z "$(strip $(MODELDOCK_MODEL))" ]; then \
		echo "MODELDOCK_MODEL is required for LIVE; select a registered local model." >&2; \
		exit 2; \
	fi

require-live-mission-inputs: require-battlestar require-modeldock-live
	@if [ -z "$(strip $(LIVE_REQUEST))" ] || [ ! -f "$(LIVE_REQUEST)" ]; then \
		echo "LIVE_REQUEST must name an existing explicit LIVE mission request." >&2; \
		exit 2; \
	fi
	@if [ -z "$(strip $(LIVE_MISSION_ID))" ]; then \
		echo "LIVE_MISSION_ID is required and must match LIVE_REQUEST." >&2; \
		exit 2; \
	fi
	@$(PYTHON) -c 'import sys; from pathlib import Path; from blackpod_build_week.contracts import MissionRequest; request = MissionRequest.from_file(Path(sys.argv[1])); valid = request.run_mode.value == "LIVE" and request.mission_id == sys.argv[2]; print("LIVE_REQUEST must be LIVE and its mission_id must equal LIVE_MISSION_ID", file=sys.stderr) if not valid else None; raise SystemExit(0 if valid else 2)' "$(LIVE_REQUEST)" "$(LIVE_MISSION_ID)"
	@if [ -z "$(strip $(LIVE_COUNCIL_POLICY))" ] || [ ! -f "$(LIVE_COUNCIL_POLICY)" ]; then \
		echo "LIVE_COUNCIL_POLICY must name an existing explicit Council policy input." >&2; \
		exit 2; \
	fi
	@if [ -z "$(strip $(LIVE_GOVERNOR_CONTEXT))" ] || [ ! -f "$(LIVE_GOVERNOR_CONTEXT)" ]; then \
		echo "LIVE_GOVERNOR_CONTEXT must name an existing explicit Governor context input." >&2; \
		exit 2; \
	fi

require-live-mission:
	@if [ -z "$(strip $(LIVE_MISSION_ID))" ]; then \
		echo "LIVE_MISSION_ID is required." >&2; \
		exit 2; \
	fi
	@if [ ! -f "$(LIVE_ARTIFACTS_ROOT)/missions/$(LIVE_MISSION_ID)/mission_snapshot.json" ]; then \
		echo "LIVE mission does not exist beneath $(LIVE_ARTIFACTS_ROOT): $(LIVE_MISSION_ID)" >&2; \
		exit 2; \
	fi

require-cabin-context-inputs: require-live-mission
	@if { [ -z "$(strip $(NAVIGATOR_MARKET_URL))" ] && [ -z "$(strip $(NAVIGATOR_MARKET_JSON))" ]; } || \
	   { [ -n "$(strip $(NAVIGATOR_MARKET_URL))" ] && [ -n "$(strip $(NAVIGATOR_MARKET_JSON))" ]; }; then \
		echo "Set exactly one of NAVIGATOR_MARKET_URL or NAVIGATOR_MARKET_JSON." >&2; \
		exit 2; \
	fi
	@if { [ -z "$(strip $(NAVIGATOR_REVISION))" ] && [ -z "$(strip $(NAVIGATOR_REPOSITORY))" ]; } || \
	   { [ -n "$(strip $(NAVIGATOR_REVISION))" ] && [ -n "$(strip $(NAVIGATOR_REPOSITORY))" ]; }; then \
		echo "Set exactly one of NAVIGATOR_REVISION or NAVIGATOR_REPOSITORY." >&2; \
		exit 2; \
	fi
	@if [ -n "$(strip $(NAVIGATOR_MARKET_JSON))" ] && [ ! -f "$(NAVIGATOR_MARKET_JSON)" ]; then \
		echo "NAVIGATOR_MARKET_JSON is not a file: $(NAVIGATOR_MARKET_JSON)" >&2; \
		exit 2; \
	fi
	@if [ -n "$(strip $(PORTFOLIO_JSON))" ] && [ ! -f "$(PORTFOLIO_JSON)" ]; then \
		echo "PORTFOLIO_JSON is not a file: $(PORTFOLIO_JSON)" >&2; \
		exit 2; \
	fi
	@if [ -z "$(strip $(CABIN_CAPTURED_AT))" ]; then \
		echo "CABIN_CAPTURED_AT is required so repeated captures remain deterministic." >&2; \
		exit 2; \
	fi

preflight-replay: require-battlestar
	$(REPLAY_ENV) $(CLI) preflight --mode replay --artifacts-root "$(DEMO_ROOT)/preflight"

preflight-live: require-battlestar require-modeldock-live
	$(LIVE_ENV) $(CLI) preflight --mode live --artifacts-root "$(LIVE_ARTIFACTS_ROOT)/preflight"

live-mission: require-live-mission-inputs
	$(LIVE_ENV) $(CLI) mission-run \
		--request "$(LIVE_REQUEST)" \
		--artifacts-root "$(LIVE_ARTIFACTS_ROOT)" \
		--with-modeldock \
		--through NAVIGATOR \
		--operator-action APPROVE_HANDOFF \
		--operator-id "$(LIVE_OPERATOR_ID)" \
		--operator-reason "$(LIVE_OPERATOR_REASON)" \
		--expires-in-minutes "$(LIVE_EXPIRES_MINUTES)" \
		--council-policy-input "$(LIVE_COUNCIL_POLICY)" \
		--governor-context-input "$(LIVE_GOVERNOR_CONTEXT)" \
		--deadline-seconds "$(LIVE_DEADLINE_SECONDS)"

package-live-demo: require-live-mission
	$(PYTHON) scripts/package_live_demo.py \
		--mission-id "$(LIVE_MISSION_ID)" \
		--artifacts-root "$(LIVE_ARTIFACTS_ROOT)" \
		--repository-root "$(BUILD_WEEK_ROOT)"

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

cabin-capture-demo: judge
	$(PYTHON) scripts/capture_cabin_context.py \
		--mission-id "$(JUDGE_MISSION_ID)" \
		--artifacts-root "$(JUDGE_ROOT)/approved" \
		--market-json "$(CABIN_DEMO_MARKET_FIXTURE)" \
		--navigator-revision "$(CABIN_DEMO_NAVIGATOR_REVISION)" \
		--market-source-identity "$(CABIN_DEMO_MARKET_SOURCE_IDENTITY)" \
		--captured-at "$(CABIN_DEMO_CAPTURED_AT)"

cabin-prepare: cabin-capture-demo
	$(PYTHON) scripts/prepare_cabin_demo.py \
		--source "$(CABIN_SOURCE)" \
		--destination "$(CABIN_DEMO_ROOT)"

cabin-prepare-demo:
	$(PYTHON) scripts/prepare_cabin_demo.py \
		--source "$(CABIN_DEMO_SOURCE)" \
		--destination "$(CABIN_DEMO_ROOT)"

cabin-capture-live: require-cabin-context-inputs
	$(PYTHON) scripts/capture_cabin_context.py \
		--mission-id "$(LIVE_MISSION_ID)" \
		--artifacts-root "$(LIVE_ARTIFACTS_ROOT)" \
		$(CABIN_MARKET_ARGUMENT) \
		$(CABIN_NAVIGATOR_REVISION_ARGUMENT) \
		--market-source-identity "$(NAVIGATOR_MARKET_SOURCE_IDENTITY)" \
		--captured-at "$(CABIN_CAPTURED_AT)" $(CABIN_PORTFOLIO_ARGUMENT)

cabin-prepare-live: package-live-demo
	$(PYTHON) scripts/prepare_cabin_demo.py \
		--source "$(CABIN_LIVE_SOURCE)" \
		--destination "$(CABIN_LIVE_ROOT)"

cabin-freeze-live-demo: package-live-demo
	$(PYTHON) scripts/prepare_cabin_demo.py \
		--source "$(CABIN_LIVE_SOURCE)" \
		--destination "$(CABIN_DEMO_ROOT)"

cabin-dev:
	$(NPM) --prefix "$(UI_DIR)" run dev

cabin-live: cabin-build
	$(CABIN_READER) $(CABIN_READER_ARGS)

cabin-reader:
	$(CABIN_READER) $(CABIN_READER_ARGS)

navigator-live: require-battlestar
	PYTHONDONTWRITEBYTECODE=1 BPN_ALPACA_LIVE_ENABLED=true BPN_ALPACA_FEED="$(ALPACA_DATA_FEED)" \
		BPN_CACHE_DIR="$(BUILD_WEEK_ROOT)/artifacts/navigator-live-cache" \
		$(PYTHON) -m uvicorn src.main:app --app-dir "$(BATTLESTAR_PATH)/blackpod-navigator-3/backend" \
		--host 127.0.0.1 --port "$(NAVIGATOR_LIVE_PORT)" --no-access-log --timeout-graceful-shutdown 5

cabin-dev-replay: cabin-prepare
	$(NPM) --prefix "$(UI_DIR)" run dev

cabin-dev-demo: cabin-prepare-demo
	$(NPM) --prefix "$(UI_DIR)" run dev

cabin-dev-live: cabin-dev

cabin-build: navigator-check
	$(NPM) --prefix "$(UI_DIR)" run build

cabin-build-replay: navigator-check cabin-prepare
	$(NPM) --prefix "$(UI_DIR)" run build:replay

cabin-build-demo: navigator-check cabin-prepare-demo
	$(NPM) --prefix "$(UI_DIR)" run build:replay

cabin-build-live: cabin-build

cabin-test: navigator-check
	$(NPM) --prefix "$(UI_DIR)" run test

cabin-e2e: navigator-check
	$(NPM) --prefix "$(UI_DIR)" run test:e2e

navigator-check:
	$(PYTHON) scripts/check_navigator_renderer.py

navigator-check-upstream: require-battlestar
	$(PYTHON) scripts/check_navigator_renderer.py --battlestar-path "$(BATTLESTAR_PATH)"
