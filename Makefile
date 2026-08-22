MDLINT ?= npx -y markdownlint-cli2
NIXIE ?= nixie
MDFORMAT_ALL ?= mdformat-all
export PATH := $(HOME)/.local/bin:$(HOME)/.bun/bin:$(PATH)
UV ?= $(shell command -v uv 2>/dev/null || printf '%s/.local/bin/uv' "$$HOME")
TOOLS = $(MDFORMAT_ALL)
VENV_TOOLS = pytest
UV_ENV = PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools
TYPOS_VERSION ?= 1.48.0
TYPOS = $(UV) tool run typos@$(TYPOS_VERSION)
SPELLING_RUFF_VERSION ?= 0.15.12
SPELLING_RUFF = $(UV) tool run --from ruff==$(SPELLING_RUFF_VERSION) ruff
PYTEST_XDIST_WORKERS ?= 1
ifeq ($(PYTEST_XDIST_WORKERS),1)
PYTEST_XDIST_ARGS :=
else
PYTEST_XDIST_ARGS := -n $(PYTEST_XDIST_WORKERS)
endif
LOCAL_K8S_ENGINE ?= docker
LOCAL_K8S_PROVIDER ?= k3d
PYLINT_PYTHON ?= pypy
PYLINT_TARGETS ?= alembic episodic openai_test_types.py tests
PYLINT_PYPY_SHIM_REF ?= 726d09f968b4d729ee4b29c71fc732e744854f3b
PYLINT_PYPY_SHIM = git+https://github.com/leynos/pylint-pypy-shim.git@$(PYLINT_PYPY_SHIM_REF)
DF12_PYTHON_LINTS_REF ?= v0.2.0
DF12_PYTHON_LINTS = git+https://github.com/leynos/df12-python-lints.git@$(DF12_PYTHON_LINTS_REF)
DF12_PYTHON ?= 3.14
PYLINT = $(UV_ENV) $(UV) tool run --python $(PYLINT_PYTHON) \
	--from '$(PYLINT_PYPY_SHIM)' pylint-pypy --load-plugins=
DF12_PYLINT_MESSAGES = R9101,C9102,R9103,R9104,C9105,C9106,C9107,R9108,R9109,R9110,R9111
DF12_PYLINT_BASE = $(UV_ENV) $(UV) run --python $(DF12_PYTHON) pylint \
	--disable=all --load-plugins=df12_python_lints
DF12_PYLINT = $(DF12_PYLINT_BASE) --enable=$(DF12_PYLINT_MESSAGES)
DF12_FUTURE_ANNOTATIONS = $(DF12_PYLINT_BASE) --enable=C9112 \
	--ignore-paths='^tests/steps/test_.*_steps[.]py$$'
AMBRLEAKS = $(UV_ENV) $(UV) tool run --python $(DF12_PYTHON) \
	--from '$(DF12_PYTHON_LINTS)' ambrleaks
SKYLOS_VERSION = 4.33.2
# Pin the tool interpreter: Skylos parses sources with its own runtime `ast`,
# so an older default Python misreads the project's 3.14 syntax.
SKYLOS = $(UV_ENV) $(UV) tool run --python 3.14 \
	--from 'skylos==$(SKYLOS_VERSION)' skylos \
	--config-file pyproject.toml
SKYLOS_PRODUCTION_TARGETS ?= alembic episodic openai_test_types.py
DUPLICATION_GATE = $(UV_ENV) $(UV) run scripts/duplication_gate.py

.PHONY: help all clean build build-release lint fmt check-fmt \
        markdownlint nixie spelling spelling-helper-test test typecheck \
        crosshair check-migrations skylos-allow validate \
        duplication duplication-test duplication-allow \
        local-k8s-up local-k8s-down local-k8s-status local-k8s-logs \
        $(TOOLS) $(VENV_TOOLS)

.DEFAULT_GOAL := all

all: build check-fmt test typecheck spelling

.venv: pyproject.toml
	$(UV_ENV) $(UV) venv --clear

build: .venv ## Build virtual-env and install deps
	$(UV_ENV) $(UV) sync --group dev

build-release: ## Build artefacts (sdist & wheel)
	python -m build --sdist --wheel

clean: ## Remove build artifacts
	rm -rf build dist *.egg-info \
	  .mypy_cache .pytest_cache .coverage coverage.* \
	  lcov.info htmlcov .venv
	find . -type d -name '__pycache__' -print0 | xargs -0 -r rm -rf

define ensure_tool
	@command -v $(1) >/dev/null 2>&1 || { \
	  printf "Error: '%s' is required, but not installed\n" "$(1)" >&2; \
	  exit 1; \
	}
endef

define ensure_tool_venv
	@$(UV_ENV) $(UV) run which $(1) >/dev/null 2>&1 || { \
	  printf "Error: '%s' is required in the virtualenv, but is not installed\n" "$(1)" >&2; \
	  exit 1; \
	}
endef

ifneq ($(strip $(TOOLS)),)
$(TOOLS): ## Verify required CLI tools
	$(call ensure_tool,$@)
endif


ifneq ($(strip $(VENV_TOOLS)),)
.PHONY: $(VENV_TOOLS)
$(VENV_TOOLS): ## Verify required CLI tools in venv
	$(call ensure_tool_venv,$@)
endif

fmt: build $(MDFORMAT_ALL) ## Format sources
	$(UV_ENV) $(UV) run ruff format
	$(UV_ENV) $(UV) run ruff check --select I --fix
	$(MDFORMAT_ALL)

check-fmt: build ## Verify formatting
	$(UV_ENV) $(UV) run ruff format --check
	# mdformat-all doesn't currently do checking

validate: ## Validate the Makefile
	mbake validate Makefile

lint: check-architecture ## Run linters
	$(UV_ENV) $(UV) run ruff check
	$(PYLINT) $(PYLINT_TARGETS)
	$(DF12_PYLINT) $(PYLINT_TARGETS)
	$(DF12_FUTURE_ANNOTATIONS) $(PYLINT_TARGETS)
	$(AMBRLEAKS) tests
	$(SKYLOS) $(SKYLOS_PRODUCTION_TARGETS) --category dead_code --gate --format concise --no-upload --no-provenance --no-grep-verify
	$(DUPLICATION_GATE) check

duplication: ## Run the blocking code-duplication gate
	$(DUPLICATION_GATE) check

duplication-test: ## Run the duplication-gate helper tests
	@$(UV_ENV) $(UV) run --no-project --python 3.13 \
		--with pytest==9.0.2 --with cyclopts --with 'pychase==0.1.0' \
		--with tomlkit \
		python -m pytest -c /dev/null --rootdir=. -p no:cacheprovider \
		scripts/tests/test_duplication_gate.py

# Accept FIRST/SECOND/REASON (and skylos NAME) only from the make command
# line: `$(value ...)` alone would silently pick up unrelated environment
# variables such as a host's exported NAME.
cli_value = $(if $(filter command line,$(origin $(1))),$(value $(1)))

duplication-allow: export DUPLICATION_FIRST = $(call cli_value,FIRST)
duplication-allow: export DUPLICATION_SECOND = $(call cli_value,SECOND)
duplication-allow: export DUPLICATION_REASON = $(call cli_value,REASON)
duplication-allow: ## Record one reasoned duplication exception
	@test -n "$${DUPLICATION_FIRST}" || { printf "Error: FIRST is required (path::qualname)\\n" >&2; exit 2; }
	@test -n "$${DUPLICATION_REASON}" || { printf "Error: REASON is required for a duplication exception\\n" >&2; exit 2; }
	$(DUPLICATION_GATE) allow --first "$${DUPLICATION_FIRST}" \
		$(if $(call cli_value,SECOND),--second "$${DUPLICATION_SECOND}",) \
		--reason "$${DUPLICATION_REASON}"

skylos-allow: export SKYLOS_NAME = $(call cli_value,NAME)
skylos-allow: export SKYLOS_REASON = $(call cli_value,REASON)
skylos-allow: ## Document one named Skylos exception, not an entry point
	@test -n "$${SKYLOS_NAME}" || { printf "Error: NAME is required for a named whitelist exception\\n" >&2; exit 2; }
	@test -n "$${SKYLOS_REASON}" || { printf "Error: REASON is required for a named whitelist exception\\n" >&2; exit 2; }
	$(SKYLOS) whitelist "$${SKYLOS_NAME}" --reason "$${SKYLOS_REASON}"

check-architecture: build ## Check hexagonal architecture import boundaries
	$(UV_ENV) $(UV) run hecate check

typecheck: build ## Run typechecking
	$(UV_ENV) $(UV) tool run ty==0.0.32 --version
	$(UV_ENV) $(UV) tool run ty==0.0.32 check

crosshair: build ## Verify CrossHair PEP 316 contracts
	$(UV_ENV) $(UV) run crosshair check --analysis_kind=PEP316 episodic/qa/chrono.py

markdownlint: spelling ## Lint Markdown files and enforce repository spelling
	env -u NO_COLOR $(MDLINT) '**/*.md'

spelling: spelling-helper-test ## Enforce en-GB-oxendict spelling in Markdown prose
	@$(UV_ENV) $(UV) run scripts/generate_typos_config.py
	@git ls-files -z '*.md' | \
		xargs -0 -r env $(UV_ENV) $(TYPOS) --config typos.toml --force-exclude

spelling-helper-test: ## Validate the shared spelling-policy integration
	@$(SPELLING_RUFF) format --check --isolated --target-version py313 \
		scripts/generate_typos_config.py scripts/typos_rollout.py \
		scripts/typos_rollout_cache.py scripts/tests/test_typos_rollout.py
	@$(SPELLING_RUFF) check --isolated --target-version py313 \
		scripts/generate_typos_config.py scripts/typos_rollout.py \
		scripts/typos_rollout_cache.py scripts/tests/test_typos_rollout.py
	@PYTHONPATH=scripts $(UV_ENV) $(UV) run --no-project --python 3.13 \
		--with pytest==9.0.2 --with pytest-cov==7.0.0 \
		python -m pytest -c /dev/null --rootdir=. -p no:cacheprovider \
		scripts/tests/test_typos_rollout.py \
		--cov=generate_typos_config --cov=typos_rollout \
		--cov=typos_rollout_cache --cov-fail-under=90

nixie: ## Validate Mermaid diagrams
	$(call ensure_tool,nixie)
	$(NIXIE) --no-sandbox

test: build crosshair $(VENV_TOOLS) ## Run tests
	$(UV_ENV) $(UV) run pytest -v $(PYTEST_XDIST_ARGS)

check-migrations: build $(VENV_TOOLS) ## Check for schema drift between models and migrations
	$(UV_ENV) $(UV) run python -m episodic.canonical.storage.migration_check

local-k8s-up: build ## Create or update the local Kubernetes preview
	$(UV_ENV) $(UV) run --group dev scripts/local_k8s.py up \
	  --engine $(LOCAL_K8S_ENGINE) --provider $(LOCAL_K8S_PROVIDER)

local-k8s-down: build ## Tear down the local Kubernetes preview
	$(UV_ENV) $(UV) run --group dev scripts/local_k8s.py down \
	  --engine $(LOCAL_K8S_ENGINE) --provider $(LOCAL_K8S_PROVIDER)

local-k8s-status: build ## Inspect the local Kubernetes preview
	$(UV_ENV) $(UV) run --group dev scripts/local_k8s.py status \
	  --engine $(LOCAL_K8S_ENGINE) --provider $(LOCAL_K8S_PROVIDER)

local-k8s-logs: build ## Show logs from the local Kubernetes preview
	$(UV_ENV) $(UV) run --group dev scripts/local_k8s.py logs \
	  --engine $(LOCAL_K8S_ENGINE) --provider $(LOCAL_K8S_PROVIDER)

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS=":"; printf "Available targets:\n"} {printf "  %-20s %s\n", $$1, $$2}'
