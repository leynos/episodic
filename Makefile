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

# The CV-005 CodeScene contracts live in shared-actions and run from a full
# commit, so a fix is a pin bump. `.github/cv005.toml` holds this repository's
# only parameters.
CV005_CONTRACTS_REF ?= a38feb9be25755c30eca5bda96bd3786a5b89c6b
CV005_CONTRACTS = $(UV_ENV) $(UV) tool run --python 3.13 \
	--from 'git+https://github.com/leynos/shared-actions@$(CV005_CONTRACTS_REF)\#subdirectory=packages/cv005-contracts' \
	cv005-contracts

TYPOS_CONFIG_BUILDER_VERSION ?= v0.1.3
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
# Pylint runs on CPython at the project's 3.14 baseline: the source uses 3.14
# syntax (PEP 758 unparenthesized `except` lists) that no managed PyPy parses.
PYLINT_PYTHON ?= 3.14
PYLINT_VERSION ?= 4.0.9
PYLINT_TARGETS ?= alembic episodic openai_test_types.py tests
TY_VERSION ?= 0.0.32
# Limit Pylint to a tenth of the available cores, with two workers minimum.
PYLINT_JOBS ?= $(shell n=$$(nproc 2>/dev/null || echo 2); \
	echo $$(( n / 10 > 2 ? n / 10 : 2 )))
DF12_PYTHON_LINTS_REF ?= v0.2.0
DF12_PYTHON_LINTS = git+https://github.com/leynos/df12-python-lints.git@$(DF12_PYTHON_LINTS_REF)
DF12_PYTHON ?= 3.14
PYLINT = $(UV_ENV) $(UV) tool run --managed-python --python $(PYLINT_PYTHON) \
	--from 'pylint==$(PYLINT_VERSION)' pylint --jobs=$(PYLINT_JOBS) --load-plugins=
DF12_PYLINT_MESSAGES = R9101,C9102,R9103,R9104,C9105,C9106,C9107,R9108,R9109,R9110,R9111
DF12_PYLINT_BASE = $(UV_ENV) $(UV) run --python $(DF12_PYTHON) pylint \
	--jobs=$(PYLINT_JOBS) --disable=all --load-plugins=df12_python_lints
DF12_PYLINT = $(DF12_PYLINT_BASE) --enable=$(DF12_PYLINT_MESSAGES)
DF12_FUTURE_ANNOTATIONS = $(DF12_PYLINT_BASE) --enable=C9112 \
	--ignore-paths='^tests/steps/test_.*_steps[.]py$$'
AMBRLEAKS = $(UV_ENV) $(UV) tool run --python $(DF12_PYTHON) \
	--from '$(DF12_PYTHON_LINTS)' ambrleaks
# The dead-code gate is the installed df12-skylos command; its `skylos` extra
# carries the one Skylos pin, and the command runs the native scan under a fixed
# hash seed. It scans the Makefile's own directory, so the scan, the allow
# helper and their lock agree when make is invoked from another working
# directory. Skylos parses source with its own runtime `ast`, so the tool
# environment runs Python 3.14.
DF12_GATES_SHA ?= b83e3eb850de93b3f9ce7fbc9ffdb429925714dc
DF12_GATES = git+https://github.com/leynos/df12-python-lints.git@$(DF12_GATES_SHA)
DF12_REPOSITORY = $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SKYLOS = $(UV_ENV) $(UV) tool run --python 3.14 --from \
	'df12-python-lints[skylos] @ $(DF12_GATES)' df12-skylos
# The duplication gate is the installed df12-duplication command. It downloads
# the nose release named by [tool.nose] version and verifies it against the
# digest table shipped in the package, so no nose pin lives here. The detector
# binary lives in .tools/nose next to the Makefile; set NOSE_BIN to run another.
NOSE_BIN ?= $(DF12_REPOSITORY)/.tools/nose/nose
DUPLICATION = $(UV_ENV) NOSE_BIN='$(NOSE_BIN)' $(UV) tool run \
	--from 'df12-python-lints[duplication] @ $(DF12_GATES)' df12-duplication

# Interrogate scans each target recursively, subject to its default exclusions
# (check a new file against the verbose report). Add a new Python directory to
# the targets. Python 3.14 is required: interrogate parses the source with the
# interpreter that runs it, and this code uses template strings.
INTERROGATE_VERSION ?= 1.7.0
INTERROGATE_TARGETS ?= alembic episodic openai_test_types.py scripts tests
# Level 2 prints a MISSED row per undocumented definition, which the
# `interrogate` target fails on: the rounded percentage alone passes a lone gap.
INTERROGATE_FLAGS ?= -vv --no-color --ext pyi --fail-under 100
INTERROGATE ?= $(UV_ENV) $(UV) tool run --python 3.14 \
	--from 'interrogate==$(INTERROGATE_VERSION)' interrogate

.PHONY: help all clean build build-release lint interrogate fmt check-fmt \
        markdownlint nixie spelling test typecheck typecheck-path \
        crosshair check-migrations skylos skylos-allow validate \
        duplication duplication-allow \
        local-k8s-up local-k8s-down local-k8s-status local-k8s-logs \
        $(TOOLS) $(VENV_TOOLS) test-workflow-contracts

.DEFAULT_GOAL := all

test-workflow-contracts: ## Check the CV-005 CodeScene workflow contracts
	$(CV005_CONTRACTS) check --repository .

all: build check-fmt test typecheck spelling test-workflow-contracts

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

interrogate: ## Enforce complete Python docstring coverage
	@report="$$($(INTERROGATE) $(INTERROGATE_FLAGS) $(INTERROGATE_TARGETS))"; \
	  status=$$?; \
	  printf '%s\n' "$$report"; \
	  test "$$status" -eq 0 || exit "$$status"; \
	  found=0; \
	  printf '%s\n' "$$report" | grep '| *MISSED *|' >/dev/null || found=$$?; \
	  if test "$$found" -ne 1; then \
	    printf '%s\n' 'interrogate: undocumented definitions remain (or the MISSED check failed); see above' >&2; \
	    exit 1; \
	  fi

lint: interrogate check-architecture skylos duplication ## Run linters
	$(UV_ENV) $(UV) run ruff check
	$(PYLINT) $(PYLINT_TARGETS)
	$(DF12_PYLINT) $(PYLINT_TARGETS)
	$(DF12_FUTURE_ANNOTATIONS) $(PYLINT_TARGETS)
	$(AMBRLEAKS) tests

skylos: ## Detect dead production code
	$(SKYLOS) check --repository $(DF12_REPOSITORY)

duplication: ## Run the blocking code-duplication gate
	$(DUPLICATION) install --repository $(DF12_REPOSITORY)
	$(DUPLICATION) check --repository $(DF12_REPOSITORY)

# Accept FIRST/SECOND/REASON (and skylos SYMBOL) only from the make command
# line. `NAME` is ambient under WSL, which injects the hostname there, so the
# Skylos interface deliberately uses the otherwise-unset `SYMBOL` variable.
cli_value = $(if $(filter command line,$(origin $(1))),$(value $(1)))

duplication-allow: export DUPLICATION_FIRST = $(call cli_value,FIRST)
duplication-allow: export DUPLICATION_SECOND = $(call cli_value,SECOND)
duplication-allow: export DUPLICATION_REASON = $(call cli_value,REASON)
duplication-allow: ## Record one reasoned duplication exception
	@case "$${DUPLICATION_FIRST}" in *[![:space:]]*) ;; *) printf 'Error: FIRST is required (path[::name])\n' >&2; exit 2;; esac
	@case "$${DUPLICATION_REASON}" in *[![:space:]]*) ;; *) printf 'Error: REASON is required for a duplication exception\n' >&2; exit 2;; esac
	@case "$${DUPLICATION_SECOND}" in *[![:print:][:space:]]*) printf 'Error: SECOND members must be printable text\n' >&2; exit 2;; esac
	@$(DUPLICATION) install --repository $(DF12_REPOSITORY)
	@set -f; set --; for key in $${DUPLICATION_SECOND}; do set -- "$$@" --second "$$key"; done; \
		$(DUPLICATION) allow --repository $(DF12_REPOSITORY) --first "$${DUPLICATION_FIRST}" "$$@" \
			--reason "$${DUPLICATION_REASON}"

skylos-allow: export SKYLOS_SYMBOL = $(call cli_value,SYMBOL)
skylos-allow: export SKYLOS_REASON = $(call cli_value,REASON)
skylos-allow: ## Document one verified Skylos exception (SYMBOL=name REASON=text)
	$(SKYLOS) allow --repository $(DF12_REPOSITORY) --symbol="$${SKYLOS_SYMBOL}" --reason="$${SKYLOS_REASON}"

check-architecture: build ## Check hexagonal architecture import boundaries
	$(UV_ENV) $(UV) run hecate check

typecheck: build ## Run typechecking
	$(UV_ENV) $(UV) tool run ty==$(TY_VERSION) --version
	$(UV_ENV) $(UV) tool run ty==$(TY_VERSION) check

typecheck-path: ## Typecheck one path using the pinned typechecker
	@test -n "$(TY_CHECK_PATH)" || { printf '%s\n' "Error: TY_CHECK_PATH is required" >&2; exit 2; }
	$(UV_ENV) $(UV) tool run ty==$(TY_VERSION) check "$(TY_CHECK_PATH)"

crosshair: build ## Verify CrossHair PEP 316 contracts
	$(UV_ENV) $(UV) run crosshair check --analysis_kind=PEP316 \
		episodic/qa/chrono.py \
		episodic/canonical/qa_artefact_validation.py

markdownlint: spelling ## Lint Markdown files and enforce repository spelling
	env -u NO_COLOR $(MDLINT) '**/*.md'

spelling: ## Enforce en-GB-oxendict spelling
	$(TYPOS_CONFIG_BUILDER) gate --repository .

nixie: ## Validate Mermaid diagrams
	$(call ensure_tool,nixie)
	$(NIXIE) --no-sandbox

test: build crosshair test-workflow-contracts $(VENV_TOOLS) ## Run tests, including the workflow contracts
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
