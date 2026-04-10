# Install dependencies
install:
    uv sync

# format
format:
    uv run ruff format .

# Run linters
lint:
    uv run ruff check .
    uv run mypy .

# Run the scraper
run:
    uv run scraper/civic_clerk.py

# Run checks then script
check: lint run
