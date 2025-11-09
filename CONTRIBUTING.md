# Contributing to Glitter

Thank you for your interest in contributing! We welcome bug reports, feature requests, documentation improvements, and code contributions.

## How to Contribute

### Reporting Issues

- Search existing issues first to avoid duplicates
- Provide clear title and description
- Include environment details (OS, Python version, installation method)
- Add steps to reproduce, expected vs. actual behavior
- Attach logs or screenshots if relevant

### Suggesting Features

- Describe the feature and its use cases
- Explain why it would benefit users
- Reference similar functionality in other tools if applicable

### Submitting Pull Requests

1. Fork the repo and create a branch from `main`
2. Follow the style guidelines below
3. Add tests for new functionality
4. Update documentation for user-facing changes
5. Ensure tests pass locally
6. Submit PR with clear description linking related issues

**PR Tips:**
- Use keywords like `Fixes #123` to link issues
- Keep changes focused (one feature/fix per PR)
- Update both English and Chinese messages in `glitter/language.py`
- Include before/after examples for user-facing changes

## Development Setup

```bash
git clone https://github.com/scarletkc/glitter.git
cd glitter
python -m venv .venv
# Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
glitter --version && python -m pytest -q
```

**Build:** `python -m build` (package) or `pyinstaller glitter.spec` (binary)

## Style Guidelines

**Git Commits:**
- Imperative mood, <50 chars subject
- Body explains what/why, not how

**Python Code:**
- Follow PEP 8: 4-space indent, type hints, docstrings
- Naming: `snake_case` (functions), `PascalCase` (classes), `UPPER_SNAKE_CASE` (constants)
- Handle specific exceptions, avoid bare `except`

**Documentation:**
- Markdown format, update README and `docs/` for user changes
- Maintain English and Chinese versions

**Testing:**
- Place tests in `tests/unit/` or `tests/integration/`
- Descriptive names: `test_<function>_<scenario>_<expected_result>`
- Keep tests fast, isolated, and deterministic
- Aim for high coverage on critical paths

## Project-Specific Notes

- See code files for detailed module organization
- Never log cryptographic keys or sensitive data
- Validate all user inputs
- User data stored in `~/.glitter/`
- Default ports
- New messages need translations in `glitter/language.py`

## Need Help?

Open an issue with your question. Check existing issues and docs first.

## Recognition

All contributors are acknowledged. Thanks for making Glitter better! 
