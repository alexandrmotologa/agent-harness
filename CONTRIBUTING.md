# Contributing to AgentHarness

Thank you for your interest in contributing to AgentHarness. This document outlines the development workflow, coding standards, and pull request process.

## Development Setup

1. Fork and clone the repository.
2. Ensure you have Python 3.12 or newer installed.
3. Install `uv` for fast dependency management if you have not already:
   ```bash
   pip install uv
   ```
4. Create an environment and install dependencies with editable mode and development packages:
   ```bash
   uv venv
   uv pip install -e ".[all]"
   uv pip install pytest pytest-asyncio pytest-cov ruff mypy
   ```

## Workflow

1. Create a descriptive feature branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Write tests covering new functionality before or alongside code changes.
3. Run the linter and test suite locally:
   ```bash
   uv run ruff check .
   uv run ruff format --check .
   uv run pytest -v
   ```
4. Commit your changes with concise, imperative commit messages:
   ```bash
   git commit -m "Add process isolation limits for Windows sandbox"
   ```
5. Push to your fork and submit a pull request against the `main` branch.

## Code Standards

- Write type hints for all public functions, methods, and classes.
- Use Pydantic v2 models for schemas and structured configuration.
- Maintain test coverage for any new sandbox engine, provider, or CLI command.
- Avoid external network calls during unit tests. Use the provided `MockProvider` or mock responses.
- Keep prose in documentation and comments direct and plain. Avoid conversational filler or decorative formatting.
