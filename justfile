set dotenv-load := false

default:
    @just --list

# Install dependencies, including the live-KiCad extra
setup:
    uv sync --all-extras

# Format code (mutates the working tree)
fmt:
    uv run ruff format .
    uv run ruff check --fix .

# Lint (non-mutating; what CI runs)
check:
    uv run ruff check .

# Run tests (tests that need kicad-cli skip when KiCad is absent)
test:
    uv run pytest

# Build the sdist and wheel into dist/
build:
    uv build
