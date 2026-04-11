FROM python:3.12-slim-bookworm
# adding uv package manager
COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

# Set the working directory in the container
WORKDIR /app

# Copy pyproject.toml and uv.lock (if you have one) first for better caching
COPY pyproject.toml uv.lock* ./

# Install dependencies using uv (syncs the project)
RUN uv sync --frozen --no-dev

# Copy the rest of the application
COPY . .

RUN useradd --create-home jtrinh && chown -R jtrinh:jtrinh /app
USER jtrinh

# Set the entry point – use uv run to respect the virtual environment
ENTRYPOINT ["uv", "run", "scraper/civic_clerk.py"]
