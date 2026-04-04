# Manchester Civic Clerk Scraper

Scraping agendas and minutes via CivicClerks API.

---

## 🛠️ Tooling Stack

I decided to move from standard legacy Python tools (`pip`, `make`, `flake8`) in favor of high-performance Rust-based alternatives:

| Tool | Purpose | Why? |
| :--- | :--- | :--- |
| **[uv](https://github.com/astral-sh/uv)** | Package Manager & Resolver | 10-100x faster than pip, creates reproducible lock files. |
| **[Ruff](https://github.com/astral-sh/ruff)** | Linter & Formatter | Replaces Flake8, isort, and Black. Extremely fast. |
| **[Mypy](https://github.com/python/mypy)** | Static Type Checker | Catches type errors before runtime. |
| **[Just](https://github.com/casey/just)** | Command Runner | Modern replacement for Make. No tab-indentation headaches. |

---

## ⚙️ Prerequisites

You need two tools installed on your system to run this project:

1.  **Uv** (Python Package Manager)
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```
2.  **Just** (Command Runner)
    *   **macOS:** `brew install just`
    *   **Linux:** `sudo apt install just` (or `cargo install just`)
    *   *Note: Do not install the Python package named `just`.*

---

## 🚀 Quick Start

1.  **Clone and Install Dependencies**
    ```bash
    git clone <repo-url>
    cd <repo-dir>

    # Uv will read pyproject.toml, create a virtual env, and install deps
    just install
    ```

2.  **Configure Environment**
    Copy `.env.example` to `.env` and fill in your API details:
    ```bash
    cp .env.example .env
    # Edit .env with your API URL and filters
    ```

3.  **Run the Scraper**
    ```bash
    just run
    ```

---

## 📋 Available Commands

We use `just` to wrap all development commands. Run `just` (with no args) to see the full list.

| Command | Description |
| :--- | :--- |
| `just install` | Install/Update project dependencies via `uv sync`. |
| `just lint` | Run Ruff (linter) and Mypy (type checker). |
| `just fix` | Auto-fix linting errors and format code with Ruff. |
| `just run` | Execute the scraper using the virtual environment. |
| `just check` | Run `lint` first, then `run` (ensures code quality before execution). |

### Development Workflow

The recommended workflow for contributing to this codebase:

1.  Write your code.
2.  Run `just fix` to auto-format and fix basic linting issues.
3.  Run `just check`. If Mypy finds a type error, fix it.
4.  Commit.

---

## 📁 Project Structure

```text
.
├── justfile              # Command recipes (The "Makefile")
├── pyproject.toml        # Project config & Tool settings (Ruff, Mypy)
├── uv.lock               # Locked dependency versions (Do not edit manually)
├── requirements.txt      # List of dependencies (Generated)
├── .env                  # Secrets and Configuration (Not in git)
├── scraper.py            # Main application logic
└── README.md             # This file
```

## ⚙️ Configuration Details

### Ruff & Mypy
Configuration is centralized in `pyproject.toml` under the `[tool.ruff]` and `[tool.mypy]` sections.

*   **Ruff:** Enforces line length (100 chars), import sorting, and specific Python version compatibility.
*   **Mypy:** Enforces strict type hints (`disallow_untyped_defs` can be toggled).

### uv
*   **Virtual Environment:** `uv` automatically manages a `.venv` in the project root. You never need to run `python -m venv` or `source .venv/bin/activate`.
*   **Execution:** `uv run scraper/civic_clerk.py` automatically uses the project's virtual environment.

