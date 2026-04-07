import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, cast

import requests
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 1. LOAD CONFIGURATION ---
load_dotenv()

ConfigDict = dict[str, Any]

CONFIG: ConfigDict = {
    "BASE_URL": os.getenv(
        "CIVIC_API_BASE_URL", "https://manchesternh.api.civicclerk.com/v1"
    ),
    "OUTPUT_DIR": os.getenv("OUTPUT_DIR", "./downloaded_minutes"),
    "COMMITTEE_FILTER": os.getenv("COMMITTEE_FILTER"),
    "START_DATE": os.getenv("START_DATE"),
    "END_DATE": os.getenv("END_DATE"),
    "DELAY": float(os.getenv("REQUEST_DELAY", "0.5")),
    "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
}

# --- 2. SETUP LOGGING ---
logging.basicConfig(
    level=getattr(logging, CONFIG["LOG_LEVEL"].upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("scraper.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

os.makedirs(CONFIG["OUTPUT_DIR"], exist_ok=True)


# --- 3. CREATE SESSION WITH RETRIES ---
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


# --- 4. HELPER: SKIP EXISTING FILES ---
def already_downloaded(filename: str) -> bool:
    """Check if file already exists in output directory."""
    return os.path.exists(os.path.join(CONFIG["OUTPUT_DIR"], filename))


# --- 5. API FUNCTIONS (with pagination) ---
def get_all_events() -> list[dict[str, Any]]:
    """Fetch all events using OData pagination (@odata.nextLink)."""
    logger.info(f"Fetching events from {CONFIG['BASE_URL']}/Events...")

    events: list[dict[str, Any]] = []
    url = f"{CONFIG['BASE_URL']}/Events"

    # Initial query parameters
    params: dict[str, str] = {
        "$orderby": "startDateTime asc, eventName asc",
    }

    # Add date filters
    filters = []
    start_date = CONFIG.get("START_DATE")
    end_date = CONFIG.get("END_DATE")

    if start_date:
        filters.append(f"startDateTime ge {start_date}")
    if end_date:
        filters.append(f"startDateTime lt {end_date}")
    if filters:
        params["$filter"] = " and ".join(filters)
        logger.info(f"Applying API Filter: {params['$filter']}")

    page_num = 1
    while url:
        logger.debug(f"Fetching page {page_num} from {url}")
        try:
            response = SESSION.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            # Extract items (OData wraps them in 'value')
            items = data.get("value", [])
            events.extend(items)
            logger.debug(
                f"Page {page_num}: got {len(items)} events (total now {len(events)})"
            )

            # Next link for pagination
            url = data.get("@odata.nextLink")
            params = None  # nextLink already contains full query
            page_num += 1

            # Respect rate limiting between pages
            if url:
                time.sleep(CONFIG["DELAY"])

        except Exception as e:
            logger.error(f"Failed to fetch events page: {e}")
            break

    logger.info(f"Successfully fetched {len(events)} events total.")
    return events


def get_event_details(event_id: int) -> dict[str, Any] | None:
    """Get detailed information for a specific event."""
    event_url = f"{CONFIG['BASE_URL']}/events/{event_id}"
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


def get_direct_download_url(file_info: dict[str, Any]) -> str | None:
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


def download_file(file_url: str, filename: str) -> bool:
    """Download a file from URL to OUTPUT_DIR/filename, skip if already exists."""
    # Check if already downloaded
    if already_downloaded(filename):
        logger.info(f"⏭️ Skipping {filename} (already exists)")
        return False

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = SESSION.get(file_url, headers=headers, stream=True, timeout=60)
        response.raise_for_status()

        # Sanity check: ensure we aren't downloading JSON as a PDF
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            logger.warning(f"⚠️ URL {file_url} returned JSON, not a PDF. Skipping.")
            logger.debug(f"JSON Content: {response.text[:200]}")
            return False

        filepath = os.path.join(CONFIG["OUTPUT_DIR"], filename)
        with open(filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        logger.info(f"✅ Downloaded: {filename}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to download {filename}: {e}")
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
        logger.warning(f"Invalid date format in .env: {date_str}. Use YYYY-MM-DD.")
        return None


# --- 6. MAIN PROCESSING LOGIC ---
def process_events(events: list[dict[str, Any]]) -> int:
    """Filter and process events based on configuration. Returns count of downloads."""
    minutes_count = 0

    start_date_obj = parse_date(CONFIG["START_DATE"])
    end_date_obj = parse_date(CONFIG["END_DATE"])
    committee_filter = CONFIG["COMMITTEE_FILTER"]

    logger.info(
        f"Filters applied -> Committee: '{committee_filter or 'All'}', "
        f"Start: {start_date_obj}, End: {end_date_obj}"
    )

    for event in events:
        event_id = event.get("id")
        if event_id is None:
            continue

        event_name = event.get("eventName", "Unknown Event")
        event_date_str = event.get("eventDate", "")
        category_name = event.get("categoryName", "Unknown Category")

        # Committee filter (case-insensitive)
        if committee_filter:
            filter_lower = committee_filter.lower()
            if (
                filter_lower not in event_name.lower()
                and filter_lower not in category_name.lower()
            ):
                continue

        logger.debug(f"Checking event: {event_name}")
        time.sleep(CONFIG["DELAY"])  # Respect rate limit

        event_details = get_event_details(event_id)
        if not event_details:
            continue

        published_files: list[dict[str, Any]] = event_details.get("publishedFiles", [])

        for file_info in published_files:
            if file_info.get("type") == "Minutes":
                real_url = get_direct_download_url(file_info)
                if real_url:
                    file_name = file_info.get("name", "minutes")
                    clean_date = (
                        event_date_str.split("T")[0] if event_date_str else "nodate"
                    )
                    safe_name = clean_filename(
                        f"{clean_date}_{category_name}_{event_name}_{file_name}.pdf"
                    )

                    if download_file(real_url, safe_name):
                        minutes_count += 1
                else:
                    logger.warning(
                        f"Could not find valid URL for minutes in event {event_id}"
                    )

    return minutes_count


def main() -> None:
    logger.info("🚀 Starting Scraper (with pagination, retries, and skip-existing)...")
    logger.info(f"Output Directory: {CONFIG['OUTPUT_DIR']}")

    events = get_all_events()
    if not events:
        logger.warning("No events found. Exiting.")
        return

    total_downloaded = process_events(events)
    logger.info(
        f"✅ Job Complete. Downloaded {total_downloaded} minute files (skipped existing)."
    )


if __name__ == "__main__":
    main()
