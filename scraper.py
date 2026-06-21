#!/usr/bin/env python3
"""
Scraper for Polish Sejm parliamentary speeches (10th term, 2023 onwards).

Extends the ParlText CEE PL_speeches dataset by fetching speech data from the
official Sejm REST API (api.sejm.gov.pl) and outputting a CSV matching the
original PL_speeches.csv format.

Usage:
    python scraper.py                          # Scrape all 10th term speeches
    python scraper.py --sitting 1              # Scrape a single sitting
    python scraper.py --sitting 1 --date 2023-11-13  # Scrape a single day
    python scraper.py --limit 5                # Scrape only first 5 sittings
"""

import argparse
import csv
import html
import logging
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = "https://api.sejm.gov.pl/sejm"
TERM = 10
ELECTORAL_CYCLE = "2023-2027"
OUTPUT_FILE = "PL_speeches_2023_onwards.csv"

# Rate limiting
DELAY_BETWEEN_SPEECHES = 0.3   # seconds between individual transcript fetches
DELAY_BETWEEN_DAYS = 1.0       # seconds between day-level requests
MAX_RETRIES = 5
BACKOFF_FACTOR = 2.0

# CSV column order matching PL_speeches.csv
CSV_COLUMNS = [
    "speech_id", "link", "agenda_item", "electoral_cycle",
    "speechnumber", "speaker", "chair", "date", "speech_text",
    "bill_id", "prediction", "prediction_name",
]

# Procedural / stage-direction markers to strip from speech text
PROCEDURAL_PATTERNS = [
    re.compile(r"^\s*\(Początek posiedzenia[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Na posiedzeniu przewodniczą[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Na salę wchodzi[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Zebrani wstają[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Oklaski\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Głos z sali[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Poruszenie na sali[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Wesołość na sali[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Dzwonek[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Koniec posiedzenia[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Przerwa[^)]*\)\s*$", re.IGNORECASE),
    re.compile(r"^\s*\(Wznawiamy[^)]*\)\s*$", re.IGNORECASE),
]

# Speaker prefix patterns to strip from beginning of speech text
# e.g. "Poseł Jan Kowalski:" or "Marszałek Sejmu Szymon Hołownia:"
SPEAKER_PREFIX_RE = re.compile(
    r"^\s*(Poseł|Minister|Prezydent|Marszałek|Senator|Sekretarz Stanu|"
    r"Prezes|Wiceprezes|Wicemarszałek|Marszałek Senior|Marszałek-Senior|"
    r"Marszałek Sejmu|Wicemarszałek Sejmu)"
    r"(\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)+\s*:\s*",
)

# Chair functions (any containing "Marszałek")
CHAIR_PATTERN = re.compile(r"Marszałek", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

session = requests.Session()
session.headers.update({
    "User-Agent": "ParlText-Extension/1.0 (research project; contact@example.com)",
    "Accept": "application/json",
})


def api_get(url: str) -> list:
    """GET a Sejm API endpoint with retries and backoff. Always returns a list."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                # Some endpoints return a dict wrapper — extract list if needed
                if isinstance(data, dict):
                    return data.get("statements", [])
                return data if isinstance(data, list) else []
            elif resp.status_code == 404:
                log.warning("404 Not Found: %s", url)
                return []
            elif resp.status_code in (429, 503):
                wait = BACKOFF_FACTOR ** attempt
                log.warning("HTTP %d — retrying in %.1fs", resp.status_code, wait)
                time.sleep(wait)
            else:
                log.warning("HTTP %d for %s", resp.status_code, url)
                time.sleep(1)
        except requests.RequestException as e:
            log.warning("Request failed (attempt %d): %s", attempt + 1, e)
            time.sleep(BACKOFF_FACTOR ** attempt)
    log.error("Giving up on %s after %d attempts", url, MAX_RETRIES)
    return []


def api_get_html(url: str) -> str:
    """GET a Sejm API endpoint that returns HTML (transcript text).

    Returns empty string on failure or if the response is not HTML."""
    # Override Accept header — transcript endpoints return text/html
    headers = {"Accept": "text/html, application/json, */*"}
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=60, headers=headers)
            if resp.status_code == 200:
                ct = resp.headers.get("Content-Type", "")
                if "html" not in ct and "text/plain" not in ct:
                    log.warning("Unexpected Content-Type %r for %s", ct, url)
                    return ""
                # Detect WAF / error pages masquerading as 200
                text = resp.text
                if "requested URL was rejected" in text.lower():
                    log.warning("WAF rejection for %s — retrying...", url[:80])
                    time.sleep(BACKOFF_FACTOR ** attempt)
                    continue
                resp.encoding = "utf-8"
                return text
            elif resp.status_code == 404:
                log.warning("404 Not Found (HTML): %s", url)
                return ""
            elif resp.status_code in (429, 503):
                wait = BACKOFF_FACTOR ** attempt
                log.warning("HTTP %d — retrying in %.1fs", resp.status_code, wait)
                time.sleep(wait)
            else:
                log.warning("HTTP %d for %s", resp.status_code, url)
                time.sleep(1)
        except requests.RequestException as e:
            log.warning("Request failed (attempt %d): %s", attempt + 1, e)
            time.sleep(BACKOFF_FACTOR ** attempt)
    log.error("Giving up on %s after %d attempts", url, MAX_RETRIES)
    return ""


# ---------------------------------------------------------------------------
# Speech text parsing
# ---------------------------------------------------------------------------

def is_procedural(text: str) -> bool:
    """Check if a paragraph is a procedural marker / stage direction."""
    stripped = text.strip()
    if not stripped:
        return True
    for pat in PROCEDURAL_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def strip_speaker_prefix(text: str) -> str:
    """Remove speaker name prefix like 'Poseł Jan Kowalski:' from start."""
    return SPEAKER_PREFIX_RE.sub("", text, count=1).strip()


def clean_text(text: str) -> str:
    """Normalize whitespace and decode HTML entities."""
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_speech_html(html_content: str) -> str:
    """
    Parse the HTML from a /transcripts/{id} response into clean speech text.

    Returns the speech text with speaker headers and procedural
    markers removed, matching the formatting of the original PL_speeches.csv.
    """
    if not html_content:
        return ""

    soup = BeautifulSoup(html_content, "html.parser")

    # Collect all <p> elements
    paragraphs = soup.find_all("p")
    if not paragraphs:
        return ""

    text_parts = []
    for p in paragraphs:
        # Skip speaker-header paragraphs (mowca-link and marsz classes)
        cls = p.get("class", [])
        if "mowca-link" in cls or "marsz" in cls:
            continue

        # Get text, preserving some structure
        para_text = p.get_text(separator=" ", strip=False)

        # Skip procedural markers / stage directions
        if is_procedural(para_text):
            continue

        # Clean and add
        cleaned = clean_text(para_text)
        if cleaned:
            text_parts.append(cleaned)

    result = " ".join(text_parts)

    # Strip the speaker prefix if it appears at the start
    result = strip_speaker_prefix(result)

    return result.strip()


# ---------------------------------------------------------------------------
# Core scraping logic
# ---------------------------------------------------------------------------

def fetch_proceedings(term: int) -> list[dict]:
    """Fetch list of all sittings for a given term."""
    url = f"{API_BASE}/term{term}/proceedings"
    log.info("Fetching sitting list for term %d...", term)
    data = api_get(url)
    if not data:
        log.error("Failed to fetch proceedings list")
        return []
    real = [p for p in data if isinstance(p, dict) and p.get("number", 0) > 0]
    log.info("Found %d sittings for term %d", len(real), term)
    return real


def fetch_transcripts(sitting: int, date: str) -> list[dict]:
    """Fetch list of statements for a specific sitting and date."""
    url = f"{API_BASE}/term{TERM}/proceedings/{sitting}/{date}/transcripts"
    statements = api_get(url)
    if not statements:
        log.warning("No statements found for sitting %d, date %s", sitting, date)
    return statements


def fetch_speech_html(sitting: int, date: str, speech_idx: int) -> str:
    """Fetch the full HTML transcript for a single speech."""
    url = f"{API_BASE}/term{TERM}/proceedings/{sitting}/{date}/transcripts/{speech_idx}"
    log.debug("Fetching speech %d for %s", speech_idx, date)
    return api_get_html(url)


def scrape_sitting(
    sitting: int,
    dates: list[str],
    writer: csv.DictWriter,
    stats: dict,
) -> None:
    """Scrape all speeches for all days of a single sitting."""
    log.info("=" * 60)
    log.info("Processing sitting %d (%d day(s))", sitting, len(dates))

    for day_idx, date_str in enumerate(dates, 1):
        log.info("  Day %d: %s", day_idx, date_str)
        time.sleep(DELAY_BETWEEN_DAYS)

        statements = fetch_transcripts(sitting, date_str)
        if not statements:
            log.warning("  No statements — skipping day")
            stats["days_skipped"] += 1
            continue

        date_formatted = date_str.replace("-", "")  # YYYYMMDD for speech_id
        running_order = 0

        for stmt in statements:
            # Unspoken entries are formal written statements (oświadczenia)
            # — they contain real speech text and SHOULD be included.
            # We track them in stats for transparency but do not skip.
            if stmt.get("unspoken", False):
                stats["unspoken_included"] += 1

            # Increment running order BEFORE fetch so numbering stays
            # sequential even if an individual speech fetch fails
            running_order += 1
            speech_idx = stmt.get("num", running_order - 1)
            speaker = stmt.get("name", "")
            function = stmt.get("function", "")

            # Determine chair status — check both function field and speaker name
            is_chair = 1 if (CHAIR_PATTERN.search(function)
                             or CHAIR_PATTERN.search(speaker)) else 0
            display_speaker = "Marszałek" if is_chair else speaker

            # Fetch full speech text
            time.sleep(DELAY_BETWEEN_SPEECHES)
            html_content = fetch_speech_html(sitting, date_str, speech_idx)

            if not html_content:
                log.warning("    Empty speech %d (%s) — skipping row", running_order, speaker)
                stats["speeches_failed"] += 1
                continue

            speech_text = parse_speech_html(html_content)

            if not speech_text:
                log.debug("    Speech %d (%s) — parsed empty", running_order, speaker)

            # Build speech_id
            speech_id = f"PL_S_{date_formatted}_{running_order:05d}"

            # Build link URL (matching 9th-term pattern with 10th-term domain)
            link = (
                f"https://www.sejm.gov.pl/Sejm{TERM}.nsf/"
                f"wypowiedz.xsp?posiedzenie={sitting}&dzien={day_idx}"
                f"&wyp={speech_idx}&view=1"
            )

            row = {
                "speech_id": speech_id,
                "link": link,
                "agenda_item": "9999",
                "electoral_cycle": ELECTORAL_CYCLE,
                "speechnumber": running_order,
                "speaker": display_speaker,
                "chair": is_chair,
                "date": date_str,
                "speech_text": speech_text,
                "bill_id": "9999",
                "prediction": 999,
                "prediction_name": "No Policy Content",
            }

            writer.writerow(row)
            stats["speeches_written"] += 1

        log.info("  Day %d complete — %d speeches written", day_idx, running_order)

    log.info("Sitting %d complete", sitting)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape Polish Sejm speeches from the REST API"
    )
    parser.add_argument(
        "--sitting", type=int, default=None,
        help="Scrape only a specific sitting number",
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Scrape only a specific date (requires --sitting)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit to first N sittings",
    )
    parser.add_argument(
        "--output", type=str, default=OUTPUT_FILE,
        help=f"Output CSV file (default: {OUTPUT_FILE})",
    )
    parser.add_argument(
        "--no-header", action="store_true",
        help="Don't write CSV header (for append mode)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Fetch sitting list but don't scrape speeches",
    )
    args = parser.parse_args()

    # --- Fetch sitting list ---
    all_sittings = fetch_proceedings(TERM)
    if not all_sittings:
        log.error("No sittings found — aborting")
        sys.exit(1)

    # --- Filter sittings ---
    if args.sitting:
        sittings = [s for s in all_sittings if s["number"] == args.sitting]
        if not sittings:
            log.error("Sitting %d not found", args.sitting)
            sys.exit(1)
        # If a specific date is given, filter dates
        if args.date:
            sittings[0]["dates"] = [args.date]
    elif args.limit:
        sittings = all_sittings[:args.limit]
    else:
        sittings = all_sittings

    total_days = sum(len(s.get("dates", [])) for s in sittings)
    log.info("Will process %d sitting(s) with %d total day(s)", len(sittings), total_days)

    if args.dry_run:
        for s in sittings:
            print(f"  Sitting {s['number']}: {s.get('title','')[:100]}")
            print(f"    Dates: {', '.join(s.get('dates',[]))}")
        log.info("Dry run complete — no data fetched")
        return

    # --- Estimate ---
    avg_speeches_per_day = 120  # rough estimate based on 9th term
    est_speeches = total_days * avg_speeches_per_day
    est_minutes = est_speeches * (DELAY_BETWEEN_SPEECHES + 0.2) / 60
    log.info("Estimated ~%d speeches, ~%.0f minutes", est_speeches, est_minutes)

    # --- Open CSV ---
    file_exists = os.path.exists(args.output) and os.path.getsize(args.output) > 0
    write_header = not args.no_header and not file_exists

    with open(args.output, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        if write_header:
            writer.writeheader()

        stats = {
            "speeches_written": 0,
            "speeches_failed": 0,
            "unspoken_included": 0,
            "days_skipped": 0,
        }

        start_time = time.time()

        for sitting_data in sittings:
            sitting_num = sitting_data["number"]
            dates = sitting_data.get("dates", [])

            if not dates:
                log.warning("Sitting %d has no dates — skipping", sitting_num)
                continue

            scrape_sitting(sitting_num, dates, writer, stats)

        elapsed = time.time() - start_time
        log.info("=" * 60)
        log.info("SCRAPE COMPLETE in %.1f minutes", elapsed / 60)
        log.info("  Speeches written:  %d", stats["speeches_written"])
        log.info("  Speeches failed:   %d", stats["speeches_failed"])
        log.info("  Unspoken included: %d", stats["unspoken_included"])
        log.info("  Days skipped:      %d", stats["days_skipped"])
        log.info("Output: %s", args.output)


if __name__ == "__main__":
    main()
