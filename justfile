# Install dependencies
install:
    uv sync

# Run linters
lint:
    uv run ruff check .
    uv run mypy .

# Run the scraper
run:
    uv run scraper/civic_clerk.py

# Run checks then script
check: lint run
