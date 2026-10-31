# Contributing to Volleymetrics MCP

Thank you for your interest in contributing to the **Volleymetrics MCP Server**!

We welcome contributions of all kinds: bug fixes, new analytical tools, documentation improvements, and performance optimizations.

---

## 🛠️ Development Setup

1. **Fork and clone the repository**:
   ```bash
   git clone https://github.com/onnobos/volleymetrics_mcp.git
   cd volleymetrics_mcp
   ```

2. **Create a virtual environment**:
   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install editable package and dev dependencies**:
   ```bash
   pip install -e ".[dev]"
   playwright install chromium
   ```

---

## 🧪 Running Tests

Before submitting a Pull Request, please ensure the entire test suite passes:

```bash
pytest -v tests/
```

To add new tests:
- Place unit tests in [`tests/`](file:///Users/onnobos/projects/volleymetrics_mcp/tests/).
- Use `pytest-asyncio` for async client and tool tests.
- Mock network calls with `unittest.mock.AsyncMock` or `pytest-httpx` to keep unit tests fast and hermetic.

---

## 🛡️ Security & Read-Only Policy

The server enforces a **strict read-only policy** on all Volleymetrics endpoints to protect user accounts and match data:
- Never implement mutating HTTP methods (`PUT`, `DELETE`, `PATCH`).
- `POST` is restricted strictly to read-like query payloads (e.g. `matchStats`, reports, or `.dvw` generation).
- Passwords must never be stored in plain text or committed to git.

---

## 📜 Pull Request Guidelines

1. Create a descriptive feature branch: `git checkout -b feat/my-new-tool`.
2. Keep commits clear and descriptive (following [Conventional Commits](https://www.conventionalcommits.org/)).
3. Update `README.md` and docstrings if adding new tools, prompts, or configuration parameters.
4. Open a Pull Request against the `master` / `main` branch.
