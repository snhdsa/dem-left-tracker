import logging
import os
import sys
import time
from datetime import datetime
from typing import Any, cast

import requests
from dotenv import load_dotenv

# --- 1. LOAD CONFIGURATION ---
load_dotenv()

# Define a Type for our configuration dictionary for clarity
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

# --- 3. API FUNCTIONS ---


def get_all_events() -> list[dict[str, Any]]:
    """Fetch events from the API, applying server-side OData filters and sorting."""
    # Use 'Events' (Capital E) to match the specific API endpoint format
    logger.info(f"Fetching events from {CONFIG['BASE_URL']}/Events...")
    events_url = f"{CONFIG['BASE_URL']}/Events"

    # 1. Sort Order: Ascending (asc) as requested in the URL example
    params: dict[str, str] = {"$orderby": "startDateTime asc, eventName asc"}

    # 2. Build Date Filter
    filters = []
    start_date = CONFIG.get("START_DATE")
    end_date = CONFIG.get("END_DATE")

    if start_date:
        filters.append(f"startDateTime ge {start_date}")

    if end_date:
        # Use 'lt' (less than) instead of 'le' (less than or equal)
        # This matches the user's requested URL pattern
        filters.append(f"startDateTime lt {end_date}")

    # If we have filters, add them to the params
    if filters:
        # Join multiple filters with "and"
        params["$filter"] = " and ".join(filters)
        logger.info(f"Applying API Filter: {params['$filter']}")

    try:
        # requests.get handles encoding spaces to '+' automatically
        response = requests.get(events_url, params=params)
        response.raise_for_status()

        data: list[dict[str, Any]] | dict[str, Any] = response.json()

        # Handle OData format vs direct list
        events: list[dict[str, Any]] = (
            data if isinstance(data, list) else data.get("value", [])
        )

        logger.info(f"Successfully fetched {len(events)} events.")
        return events
    except Exception as e:
        logger.error(f"Critical error fetching events: {e}")
        sys.exit(1)


def get_event_details(event_id: int) -> dict[str, Any] | None:
    """Get detailed information for a specific event."""
    event_url = f"{CONFIG['BASE_URL']}/events/{event_id}"
    try:
        response = requests.get(event_url)
        response.raise_for_status()
        data = response.json()

        # Ensure we got a dictionary
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
    streamUrl contains the direct link to the blob, while url gives an authenticated
    url to the blob.
    """
    possible_keys = [
        "streamUrl",
    ]

    for key in possible_keys:
        if key in file_info and file_info[key]:
            return cast("str", file_info[key])

    # 2. Fallback: Try the standard 'url' field
    # BUT, we must check if it returns JSON or redirects.
    # If we already downloaded the JSON, we can parse it here.

    # Note: Since the user manually found 'blobUri' in the downloaded file,
    # the 'url' field likely points to an endpoint that returns this JSON.
    # We can actually request that URL to get the blobUri dynamically!

    api_url = file_info.get("url")
    if api_url:
        try:
            # We make a quick HEAD request to see if it's JSON, or a GET
            # Since we know it returns JSON based on your finding:
            logger.debug(f"Checking URL for redirect/blob: {api_url}")
            resp = requests.get(api_url, timeout=10)

            if resp.status_code == 200:
                # Check if content is JSON
                if "application/json" in resp.headers.get("Content-Type", ""):
                    json_data = resp.json()
                    # Look for the blobUri in the response
                    if "blobUri" in json_data:
                        return cast("str", json_data["blobUri"])
                    if "url" in json_data:
                        return cast("str", json_data["url"])  # recursive check
                else:
                    # It's likely a direct file (PDF)
                    return cast("str", api_url)
        except Exception as e:
            logger.debug(f"Could not resolve URL {api_url}: {e}")

    return None


def download_file(file_url: str, filename: str) -> bool:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        response = requests.get(file_url, headers=headers, stream=True)
        response.raise_for_status()

        # Sanity Check: Ensure we aren't downloading JSON as a PDF
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            logger.warning(f"⚠️  URL {file_url} returned JSON, not a PDF. Skipping.")
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


# --- 4. MAIN LOGIC ---


def process_events(events: list[dict[str, Any]]) -> int:
    """Filter and process events based on configuration. Returns count of downloads."""
    minutes_count = 0

    start_date_obj = parse_date(CONFIG["START_DATE"])
    end_date_obj = parse_date(CONFIG["END_DATE"])
    committee_filter = CONFIG["COMMITTEE_FILTER"]

    logger.info(
        f"Filters applied -> Committee: '{committee_filter or 'All'}', "
        f"''Start: {start_date_obj}, End: {end_date_obj}"
    )

    for event in events:
        event_id = event.get("id")
        if event_id is None:
            continue

        event_name = event.get("eventName", "Unknown Event")
        event_date_str = event.get("eventDate", "")
        category_name = event.get("categoryName", "Unknown Category")

        if committee_filter:
            filter_lower = committee_filter.lower()
            if (
                filter_lower not in event_name.lower()
                and filter_lower not in category_name.lower()
            ):
                continue

        # --- PROCESSING ---
        logger.debug(f"Checking event: {event_name}")
        time.sleep(CONFIG["DELAY"])

        event_details = get_event_details(event_id)
        if not event_details:
            continue

        published_files: list[dict[str, Any]] = event_details.get("publishedFiles", [])

        for file_info in published_files:
            if file_info.get("type") == "Minutes":
                # 1. Try to find the real URL
                real_url = get_direct_download_url(file_info)

                if real_url:
                    file_name = file_info.get("name", "minutes")
                    clean_date = (
                        event_date_str.split("T")[0] if event_date_str else "nodate"
                    )
                    safe_name = clean_filename(
                        f"{clean_date}_{category_name}_{event_name}_{file_name}.pdf"
                    )

                    # 2. Download
                    if download_file(real_url, safe_name):
                        minutes_count += 1
                else:
                    logger.warning(
                        f"Could not find valid URL for minutes in event {event_id}"
                    )
    return minutes_count


def main() -> None:
    logger.info("🚀 Starting Scraper...")

    logger.info(f"Output Directory: {CONFIG['OUTPUT_DIR']}")

    events = get_all_events()
    if not events:
        logger.warning("No events found. Exiting.")
        return

    total_downloaded = process_events(events)
    logger.info(f"✅ Job Complete. Downloaded {total_downloaded} minute files.")


if __name__ == "__main__":
    main()
