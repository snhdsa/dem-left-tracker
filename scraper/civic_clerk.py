import logging
import os
import re
import time
from datetime import datetime
from typing import Annotated, Any, cast
from urllib.parse import urlparse

import requests
import typer
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from urllib3.util.retry import Retry

app = typer.Typer(help="CivicClerk municipal minutes scraper")
console = Console()

# --- 1. LOAD CONFIGURATION ---
load_dotenv()

ConfigDict = dict[str, Any]


def get_config(
    base_url: str | None = None,
    output_dir: str | None = None,
    committee_filter: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    request_delay: float | None = None,
) -> ConfigDict:
    return {
        "BASE_URL": base_url
        or os.getenv(
            "CIVIC_API_BASE_URL", "https://manchesternh.api.civicclerk.com/v1"
        ),
        "OUTPUT_DIR": output_dir or os.getenv("OUTPUT_DIR", "./downloaded_minutes"),
        "COMMITTEE_FILTER": committee_filter or os.getenv("COMMITTEE_FILTER"),
        "START_DATE": start_date or os.getenv("START_DATE"),
        "END_DATE": end_date or os.getenv("END_DATE"),
        "DELAY": float(
            request_delay
            if request_delay is not None
            else os.getenv("REQUEST_DELAY", "0.5")
        ),
    }


# --- 2. SETUP LOGGING ---
def setup_logging(log_level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, console=console)],
    )


logger = logging.getLogger(__name__)


def create_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = create_session()


def get_first_subdomain(url: str) -> str:
    # Ensure a scheme exists for proper parsing
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Invalid URL, no hostname found")
    # Split hostname by dots and take the first part
    return hostname.split(".")[0]


def already_downloaded(output_dir: str, relative_path: str) -> bool:
    """Check if file already exists in output directory using a relative path."""
    full_path = os.path.join(output_dir, relative_path)
    return os.path.exists(full_path)


# --- 5. API FUNCTIONS (with pagination) ---
def get_all_events(
    base_url: str, date_filter: str | None, delay: float
) -> list[dict[str, Any]]:
    """Fetch all events using OData pagination (@odata.nextLink)."""
    logger.info(f"Fetching events from {base_url}/Events...")

    events: list[dict[str, Any]] = []
    url = f"{base_url}/Events"

    # Initial query parameters
    params: dict[str, str] = {
        "$orderby": "startDateTime asc, eventName asc",
    }

    # Add date filters
    if date_filter:
        params["$filter"] = date_filter
        logger.info(f"Applying API Filter: {params['$filter']}")

    page_num = 1
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching events...", total=None)

        while url:
            progress.update(task, description=f"Fetching page {page_num}...")
            logger.debug(f"Fetching page {page_num} from {url}")
            try:
                response = SESSION.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()

                # Extract items (OData wraps them in 'value')
                items = data.get("value", [])
                events.extend(items)
                logger.debug(
                    f"Page {page_num}: got {len(items)} events "
                    f"(total now {len(events)})"
                )

                # Next link for pagination
                url = data.get("@odata.nextLink")
                params = {}  # nextLink already contains full query
                page_num += 1

                # Respect rate limiting between pages
                if url:
                    time.sleep(delay)

            except Exception as e:
                logger.error(f"Failed to fetch events page: {e}")
                break

    logger.info(f"Successfully fetched {len(events)} events total.")
    return events


def get_event_details(event_id: int, base_url: str) -> dict[str, Any] | None:
    """Get detailed information for a specific event."""
    event_url = f"{base_url}/events/{event_id}"
    try:
        response = SESSION.get(event_url, timeout=30)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            return data
        else:
            logger.warning(
                f"Event {event_id} returned unexpected data type: {type(data)}"
            )
            return None
    except Exception as e:
        logger.warning(f"Failed to fetch details for event ID {event_id}: {e}")
        return None


def get_direct_download_url(file_info: dict[str, Any], base_url: str) -> str | None:
    """
    Extract the actual download URL from the file info.
    Prefers 'streamUrl', otherwise resolves the 'url' field.
    """
    # 1. Direct stream URL
    if "streamUrl" in file_info and file_info["streamUrl"]:
        return cast("str", file_info["streamUrl"])

    # 2. Try to resolve the 'url' field (may return JSON with blobUri)
    api_url = file_info.get("url")
    if api_url:
        try:
            logger.debug(f"Resolving URL: {api_url}")
            resp = SESSION.get(api_url, timeout=10)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    json_data = resp.json()
                    # Look for blobUri (observed in earlier manual check)
                    if "blobUri" in json_data:
                        return cast("str", json_data["blobUri"])
                    if "url" in json_data:
                        return cast("str", json_data["url"])
                else:
                    # Direct file (PDF)
                    return cast("str", api_url)
        except Exception as e:
            logger.debug(f"Could not resolve URL {api_url}: {e}")

    return None


def download_file(file_url: str, output_dir: str, relative_path: str) -> bool:
    """
    Download a file from URL to OUTPUT_DIR/relative_path.
    Creates any necessary subdirectories.
    """
    # Check if already downloaded
    if already_downloaded(output_dir, relative_path):
        return False

    full_path = os.path.join(output_dir, relative_path)
    # Create the subdirectory if it doesn't exist
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"  # noqa: E501
        }
        response = SESSION.get(file_url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()

        # Sanity check: ensure we aren't downloading JSON as a PDF
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            logger.warning(f"URL {file_url} returned JSON, not a PDF. Skipping.")
            logger.debug(f"JSON Content: {response.text[:200]}")
            return False

        with open(full_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"Downloaded: {relative_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to download {relative_path}: {e}")
        return False


def clean_filename(name: str) -> str:
    """Remove invalid characters from filename."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    return name[:150]


def parse_date(date_str: str | None) -> datetime | None:
    """Safely parse a date string or return None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        logger.warning(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
        return None


def build_date_filter(start_date: str | None, end_date: str | None) -> str | None:
    """Build OData $filter expression for date range."""
    filters = []
    if start_date:
        filters.append(f"startDateTime ge {start_date}")
    if end_date:
        filters.append(f"startDateTime lt {end_date}")
    return " and ".join(filters) if filters else None


# --- 6. MAIN PROCESSING LOGIC (modified to build relative paths) ---
def process_events(
    events: list[dict[str, Any]],
    config: ConfigDict,
    base_url: str,
    progress: Progress | None = None,
) -> int:
    """Filter and process events based on configuration. Returns count of downloads."""
    minutes_count = 0

    municipality = get_first_subdomain(base_url)
    start_date_obj = parse_date(config["START_DATE"])
    year = str(start_date_obj.year) if start_date_obj else "unknown"
    committee_filter = config["COMMITTEE_FILTER"]
    committee_regex = re.compile(r"(?:(Special )?Committee on .*)")

    logger.info(
        f"Filters applied -> Committee: '{committee_filter or 'All'}', "
        f"Start: {start_date_obj}, End: {parse_date(config['END_DATE'])}"
    )

    task_id = None
    if progress:
        task_id = progress.add_task("Processing events...", total=len(events))

    for event in events:
        event_id = event.get("id")
        if event_id is None:
            continue

        event_name = event.get("eventName", "Unknown Event")
        category_name = event.get("categoryName", "Unknown Category")

        # Manchester NH does not store the committee name in the categoryName field
        # which is always set to "Board of Aldermen". Instead they use the event_name
        # for that value fairly consistently so we can use this as a backup.
        if category_name == "Board of Mayor and Aldermen":
            match = committee_regex.search(event_name)
            if match:
                category_name = match.group(0)

        # Committee filter (case-insensitive)
        if committee_filter:
            filter_lower = committee_filter.lower()
            if (
                filter_lower not in event_name.lower()
                and filter_lower not in category_name.lower()
            ):
                if progress and task_id is not None:
                    progress.update(task_id, advance=1)
                continue

        logger.debug(f"Checking event: {event_name}")
        time.sleep(config["DELAY"])  # Respect rate limit

        event_details = get_event_details(event_id, base_url)
        if not event_details:
            if progress and task_id is not None:
                progress.update(task_id, advance=1)
            continue

        published_files: list[dict[str, Any]] = event_details.get("publishedFiles", [])

        for file_info in published_files:
            if file_info.get("type") == "Minutes":
                real_url = get_direct_download_url(file_info, base_url)
                if real_url:
                    file_name = file_info.get("name", "minutes")
                    # Sanitize category name for use as a folder name
                    safe_category = clean_filename(category_name)
                    safe_filename = clean_filename(f"{file_name}.pdf")
                    # Build relative path: category_folder / filename
                    relative_path = os.path.join(
                        municipality, year, safe_category, safe_filename
                    )

                    if download_file(real_url, config["OUTPUT_DIR"], relative_path):
                        minutes_count += 1
                else:
                    logger.warning(
                        f"Could not find valid URL for minutes in event {event_id}"
                    )

        if progress and task_id is not None:
            progress.update(task_id, advance=1)

    return minutes_count


@app.command()
def run(
    # cli args
    base_url: Annotated[
        str,
        typer.Argument(
            help="CivicClerk API base URL. For example: "
            "https://manchesternh.api.civicclerk.com/v1"
        ),
    ],
    # cli options
    # required options (haha)
    start_date: Annotated[
        str, typer.Option("--start-date", "-s", help="Start date (YYYY-MM-DD)")
    ],
    # optional options (what do words even mean any more, folks?)
    output_dir: Annotated[
        str,
        typer.Option("--output-dir", "-o", help="Directory to save downloaded minutes"),
    ] = "./downloaded_minutes",
    end_date: Annotated[
        str, typer.Option("--end-date", "-e", help="End date (YYYY-MM-DD)")
    ] = None,
    committee_filter: Annotated[
        str,
        typer.Option(
            "--committee-filter",
            "-c",
            help="Filter by committee name (substring match)",
        ),
    ] = None,
    request_delay: Annotated[
        float,
        typer.Option("--delay", "-d", help="Delay between requests (seconds)"),
    ] = None,
    log_level: Annotated[
        str, typer.Option("--log-level", "-l", help="Logging verbosity")
    ] = "INFO",
) -> None:
    """Download municipal meeting minutes from CivicClerk APIs.

    Many municipal governments,
    """
    setup_logging(log_level)

    if start_date is None:
        raise typer.Exit(1)

    config = get_config(
        base_url=base_url,
        output_dir=output_dir,
        committee_filter=committee_filter,
        start_date=start_date,
        end_date=end_date,
        request_delay=request_delay,
    )

    os.makedirs(config["OUTPUT_DIR"], exist_ok=True)

    date_filter = build_date_filter(config["START_DATE"], config["END_DATE"])

    logger.info("Starting scraper (with pagination, retries, and skip-existing)...")
    logger.info(f"Output Directory: {config['OUTPUT_DIR']}")

    events = get_all_events(config["BASE_URL"], date_filter, config["DELAY"])
    if not events:
        logger.warning("No events found. Exiting.")
        raise typer.Exit(1)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        total_downloaded = process_events(events, config, config["BASE_URL"], progress)

    logger.info(
        f"Job complete. Downloaded {total_downloaded} minute files (skipped existing)."
    )


if __name__ == "__main__":
    app()
