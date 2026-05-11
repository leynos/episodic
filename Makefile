MDLINT ?= npx -y markdownlint-cli2
NIXIE ?= nixie
MDFORMAT_ALL ?= mdformat-all
export PATH := $(HOME)/.local/bin:$(HOME)/.bun/bin:$(PATH)
UV ?= $(shell command -v uv 2>/dev/null || printf '%s/.local/bin/uv' "$$HOME")
TOOLS = $(MDFORMAT_ALL)
VENV_TOOLS = pytest
UV_ENV = PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 UV_CACHE_DIR=.uv-cache UV_TOOL_DIR=.uv-tools
PYTEST_XDIST_WORKERS ?= 1
PYLINT_PYTHON ?= pypy
PYLINT_TARGETS ?= alembic episodic openai_test_types.py tests
PYLINT = $(UV_ENV) $(UV) tool run --python $(PYLINT_PYTHON) --from 'pylint==4.*' python tools/pylint_pypy.py
PYLINT_ENABLE = logging-unsupported-format,logging-format-truncated,logging-too-many-args,logging-too-few-args,logging-not-lazy,logging-format-interpolation,logging-fstring-interpolation,bare-name-capture-pattern,invalid-match-args-definition,too-many-positional-sub-patterns,multiple-class-sub-patterns,match-class-bind-self,match-class-positional-attributes,consider-merging-isinstance,too-many-nested-blocks,simplifiable-if-statement,redefined-argument-from-local,no-else-return,consider-using-ternary,trailing-comma-tuple,stop-iteration-return,simplify-boolean-expression,inconsistent-return-statements,useless-return,consider-swap-variables,consider-using-join,consider-using-in,consider-using-get,chained-comparison,consider-using-dict-comprehension,consider-using-set-comprehension,simplifiable-if-expression,no-else-raise,unnecessary-comprehension,consider-using-sys-exit,no-else-break,no-else-continue,super-with-arguments,simplifiable-condition,condition-evals-to-constant,consider-using-generator,use-a-generator,consider-using-min-builtin,consider-using-max-builtin,consider-using-with,unnecessary-dict-index-lookup,use-list-literal,use-dict-literal,unnecessary-list-index-lookup,use-yield-from,unnecessary-negation,consider-using-enumerate,consider-iterating-dictionary,consider-using-dict-items,use-maxsplit-arg,use-sequence-for-iteration,consider-using-f-string,use-implicit-booleaness-not-len,use-implicit-booleaness-not-comparison,use-implicit-booleaness-not-comparison-to-string,use-implicit-booleaness-not-comparison-to-zero,unnecessary-dunder-call,unnecessary-ellipsis,invalid-envvar-value,singledispatch-method,singledispatchmethod-function,bad-open-mode,boolean-datetime,redundant-unittest-assert,bad-thread-instantiation,shallow-copy-environ,invalid-envvar-default,subprocess-popen-preexec-fn,subprocess-run-check,unspecified-encoding,forgotten-debug-statement,method-cache-max-size-none,deprecated-method,deprecated-argument,deprecated-class,deprecated-decorator,deprecated-attribute,too-many-lines,trailing-whitespace,missing-final-newline,trailing-newlines,superfluous-parens,mixed-line-endings,unexpected-line-ending-format,modified-iterating-dict,modified-iterating-set,modified-iterating-list,too-many-public-methods,too-many-branches,too-many-arguments,too-many-locals,too-many-statements,too-many-boolean-expressions,too-many-positional-arguments

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

lint: check-architecture ## Run linters
	$(UV_ENV) $(UV) run ruff check
	$(PYLINT) --disable=all --enable=$(PYLINT_ENABLE) --disable=syntax-error --max-locals=20 $(PYLINT_TARGETS)

check-architecture: build ## Check hexagonal architecture import boundaries
	$(UV_ENV) $(UV) run python -m episodic.architecture

typecheck: build ## Run typechecking
	$(UV_ENV) $(UV) tool run ty==0.0.32 --version
	$(UV_ENV) $(UV) tool run ty==0.0.32 check

markdownlint: ## Lint Markdown files
	env -u NO_COLOR $(MDLINT) '**/*.md'

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
