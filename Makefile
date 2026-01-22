# Makefile for Chantal - Run CI/CD checks locally
# This Makefile mirrors the checks run in .github/workflows/lint-and-type-check.yml

# Configuration
PYTHON := python3
SRC_DIR := src/chantal
TEST_DIR := tests
EXAMPLES_DIR := examples
GITHUB_DIR := .github

# Colors for output
COLOR_RESET := \033[0m
COLOR_BOLD := \033[1m
COLOR_GREEN := \033[32m
COLOR_YELLOW := \033[33m
COLOR_BLUE := \033[34m

# Phony targets
.PHONY: help check lint test format ruff black yamllint mypy pytest clean install-dev

# Default target
help:
	@echo "$(COLOR_BOLD)Chantal Development Makefile$(COLOR_RESET)"
	@echo ""
	@echo "$(COLOR_BOLD)Usage:$(COLOR_RESET)"
	@echo "  make $(COLOR_GREEN)check$(COLOR_RESET)       - Run all CI/CD checks (lint + test)"
	@echo "  make $(COLOR_GREEN)lint$(COLOR_RESET)        - Run all linters (ruff, black, yamllint, mypy)"
	@echo "  make $(COLOR_GREEN)test$(COLOR_RESET)        - Run pytest"
	@echo "  make $(COLOR_GREEN)format$(COLOR_RESET)      - Auto-format code (black + ruff --fix)"
	@echo ""
	@echo "$(COLOR_BOLD)Individual linters:$(COLOR_RESET)"
	@echo "  make $(COLOR_YELLOW)ruff$(COLOR_RESET)       - Run ruff linter"
	@echo "  make $(COLOR_YELLOW)black$(COLOR_RESET)      - Check code formatting with black"
	@echo "  make $(COLOR_YELLOW)yamllint$(COLOR_RESET)   - Lint YAML files"
	@echo "  make $(COLOR_YELLOW)mypy$(COLOR_RESET)       - Run type checker"
	@echo "  make $(COLOR_YELLOW)pytest$(COLOR_RESET)     - Run tests with pytest"
	@echo ""
	@echo "$(COLOR_BOLD)Utilities:$(COLOR_RESET)"
	@echo "  make $(COLOR_BLUE)install-dev$(COLOR_RESET) - Install development dependencies"
	@echo "  make $(COLOR_BLUE)clean$(COLOR_RESET)       - Remove build artifacts and cache"

# Main targets
check: lint test
	@echo "$(COLOR_GREEN)$(COLOR_BOLD)✓ All CI/CD checks passed!$(COLOR_RESET)"

lint: ruff black yamllint mypy
	@echo "$(COLOR_GREEN)$(COLOR_BOLD)✓ All linters passed!$(COLOR_RESET)"

test: pytest

# Individual linter targets (matching CI/CD workflow)
ruff:
	@echo "$(COLOR_BOLD)Running ruff linter...$(COLOR_RESET)"
	@ruff check $(SRC_DIR) $(TEST_DIR)

black:
	@echo "$(COLOR_BOLD)Checking code formatting with black...$(COLOR_RESET)"
	@black --check --diff $(SRC_DIR) $(TEST_DIR)

yamllint:
	@echo "$(COLOR_BOLD)Linting YAML files...$(COLOR_RESET)"
	@yamllint --strict $(EXAMPLES_DIR) $(GITHUB_DIR)

mypy:
	@echo "$(COLOR_BOLD)Running mypy type checker...$(COLOR_RESET)"
	@mypy $(SRC_DIR) --ignore-missing-imports

pytest:
	@echo "$(COLOR_BOLD)Running pytest...$(COLOR_RESET)"
	@pytest $(TEST_DIR) -v --tb=short

# Formatting target
format:
	@echo "$(COLOR_BOLD)Auto-formatting code...$(COLOR_RESET)"
	@black $(SRC_DIR) $(TEST_DIR)
	@ruff check --fix $(SRC_DIR) $(TEST_DIR)
	@echo "$(COLOR_GREEN)$(COLOR_BOLD)✓ Code formatted!$(COLOR_RESET)"

# Utility targets
install-dev:
	@echo "$(COLOR_BOLD)Installing development dependencies...$(COLOR_RESET)"
	@$(PYTHON) -m pip install --upgrade pip
	@pip install -e ".[dev]"
	@echo "$(COLOR_GREEN)$(COLOR_BOLD)✓ Development dependencies installed!$(COLOR_RESET)"

clean:
	@echo "$(COLOR_BOLD)Cleaning build artifacts and cache...$(COLOR_RESET)"
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@rm -rf build/ dist/ 2>/dev/null || true
	@echo "$(COLOR_GREEN)$(COLOR_BOLD)✓ Cleaned!$(COLOR_RESET)"
