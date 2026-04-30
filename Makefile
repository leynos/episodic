MDLINT ?= npx -y markdownlint-cli2
NIXIE ?= nixie
MDFORMAT_ALL ?= mdformat-all
UV ?= $(shell command -v uv 2>/dev/null || printf '/home/leynos/.local/bin/uv')
TOOLS = $(MDFORMAT_ALL)
VENV_TOOLS = pytest
UV_ENV = PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools
PYTEST_XDIST_WORKERS ?= 1

.PHONY: help all clean build build-release lint fmt check-fmt \
        markdownlint nixie test typecheck check-migrations $(TOOLS) $(VENV_TOOLS)

.DEFAULT_GOAL := all

all: build check-fmt test typecheck

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

lint: build check-architecture ## Run linters
	$(UV_ENV) $(UV) run ruff check

check-architecture: build ## Check hexagonal architecture import boundaries
	$(UV_ENV) $(UV) run python -m episodic.architecture

typecheck: build ## Run typechecking
	$(UV_ENV) $(UV) tool run ty==0.0.32 --version
	$(UV_ENV) $(UV) tool run ty==0.0.32 check

markdownlint: ## Lint Markdown files
	$(MDLINT) '**/*.md'

nixie: ## Validate Mermaid diagrams
	$(call ensure_tool,nixie)
	$(NIXIE) --no-sandbox

test: build $(VENV_TOOLS) ## Run tests
	$(UV_ENV) $(UV) run pytest -v -n $(PYTEST_XDIST_WORKERS)

check-migrations: build $(VENV_TOOLS) ## Check for schema drift between models and migrations
	$(UV_ENV) $(UV) run python -m episodic.canonical.storage.migration_check

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS=":"; printf "Available targets:\n"} {printf "  %-20s %s\n", $$1, $$2}'
