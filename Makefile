MDLINT ?= $(shell command -v markdownlint-cli2 2>/dev/null || printf '%s' "$$HOME/.bun/bin/markdownlint-cli2")
# `make fmt` and `make check-fmt` call mdtablefix directly. `--git` selects the
# Markdown files Git tracks and `--include-untracked` adds the untracked files
# Git does not ignore, so a new document is formatted before it is staged.
# Both modes need mdtablefix 0.6.0 or later; CI pins the version at the
# install-mdtablefix step.
MDTABLEFIX ?= mdtablefix
MDTABLEFIX_SELECT = --git --include-untracked
MDTABLEFIX_RULES = --wrap --renumber --breaks --ellipsis --fences
NIXIE ?= nixie
export PATH := $(HOME)/.local/bin:$(HOME)/.bun/bin:$(PATH)
UV ?= $(shell command -v uv 2>/dev/null || printf '%s/.local/bin/uv' "$$HOME")
TOOLS =
VENV_TOOLS = pytest
UV_ENV = PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools
TYPOS_CONFIG_BUILDER_VERSION ?= v0.1.1
TYPOS_CONFIG_BUILDER = $(UV) tool run --from \
	"git+https://github.com/leynos/typos-config-builder.git@$(TYPOS_CONFIG_BUILDER_VERSION)" \
	typos-config-builder
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
SKYLOS = $(UV_ENV) $(UV) tool run --from 'skylos==$(SKYLOS_VERSION)' skylos \
	--config-file pyproject.toml
SKYLOS_PRODUCTION_TARGETS ?= alembic episodic openai_test_types.py

.PHONY: help all clean build build-release lint fmt check-fmt \
        markdownlint nixie spelling test typecheck \
        crosshair check-migrations skylos-allow validate \
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

fmt: build ## Format sources
	$(UV_ENV) $(UV) run ruff format
	$(UV_ENV) $(UV) run ruff check --select I --fix
	$(MDTABLEFIX) --in-place $(MDTABLEFIX_SELECT) $(MDTABLEFIX_RULES)
	@unset FORCE_COLOR; $(MDLINT) --fix "**/*.md"

check-fmt: build ## Verify formatting
	$(UV_ENV) $(UV) run ruff format --check
	$(MDTABLEFIX) --check $(MDTABLEFIX_SELECT) $(MDTABLEFIX_RULES)

validate: ## Validate the Makefile
	mbake validate Makefile

lint: check-architecture ## Run linters
	$(UV_ENV) $(UV) run ruff check
	$(PYLINT) $(PYLINT_TARGETS)
	$(DF12_PYLINT) $(PYLINT_TARGETS)
	$(DF12_FUTURE_ANNOTATIONS) $(PYLINT_TARGETS)
	$(AMBRLEAKS) tests
	$(SKYLOS) $(SKYLOS_PRODUCTION_TARGETS) --category dead_code --gate --format concise --no-upload --no-provenance --no-grep-verify

skylos-allow: export SKYLOS_NAME = $(value NAME)
skylos-allow: export SKYLOS_REASON = $(value REASON)
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

spelling: ## Enforce en-GB-oxendict spelling
	$(TYPOS_CONFIG_BUILDER) gate --repository .

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
