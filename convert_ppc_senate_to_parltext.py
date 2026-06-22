#!/usr/bin/env python3
"""
Converter: Polish Parliamentary Corpus (PPC) Senate TEI → ParlText CSV.

Reads PPC Senate TEI P5 XML data and produces a CSV matching the ParlText
PL_speeches.csv format.  Works with any PPC term (2015–2019, 2019–2023,
2023–2027, etc.).  The electoral cycle and term number are auto-detected
from the input directory path.

The PPC data is expected at paths like: ppc_2015_2019_tei/2015-2019/senat/posiedzenia/pp/

Usage:
    python convert_ppc_senate_to_parltext.py
    python convert_ppc_senate_to_parltext.py --input-dir path/to/pp/data
    python convert_ppc_senate_to_parltext.py --output my_output.csv
    python convert_ppc_senate_to_parltext.py --dry-run
"""

import argparse
import csv
import logging
import os
import re
import sys

from lxml import etree

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_INPUT_DIR = os.path.join(
    "ppc_2023_2027_tei", "2023-2027", "senat", "posiedzenia", "pp"
)
DEFAULT_OUTPUT_FILE = "PL_speeches_senat_2023_onwards.csv"

# Senate term number by year range (for URL construction)
SENATE_TERM_BY_YEARS = {
    "1989-1991": 1, "1991-1993": 2, "1993-1997": 3,
    "1997-2001": 4, "2001-2005": 5, "2005-2007": 6,
    "2007-2011": 7, "2011-2015": 8, "2015-2019": 9,
    "2019-2023": 10, "2023-2027": 11,
}

# CSV column order matching PL_speeches.csv
CSV_COLUMNS = [
    "speech_id", "link", "agenda_item", "electoral_cycle",
    "speechnumber", "speaker", "chair", "date", "speech_text",
    "bill_id", "prediction", "prediction_name",
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ppc_converter")

# ---------------------------------------------------------------------------
# XML parsing helpers
# ---------------------------------------------------------------------------

# Chair detection: Senate presiding officers only
# Valid chair roles: "Marszałek", "Wicemarszałek", "Marszałek Senior"
# Excludes: "Marszałek Sejmu RP" (guest), "Marszałek Województwa ..." (regional)
CHAIR_ROLES = {"Marszałek", "Wicemarszałek", "Marszałek Senior"}


def _text(el) -> str:
    """Get the full text content of an element."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def _find_all(root, tag: str):
    """Find all elements matching tag regardless of namespace."""
    return root.xpath(f"//*[local-name()='{tag}']")


def _find_all_in(el, tag: str):
    """Find all descendant elements matching tag regardless of namespace."""
    return el.xpath(f".//*[local-name()='{tag}']")


def _parse_xml(file_path: str):
    """
    Parse an XML file with encoding fallback.

    Older PPC files may use Windows-1250 or ISO-8859-2 instead of UTF-8.
    Tries UTF-8 first, then common Polish encodings.
    """
    # Encodings to try, in order
    encodings = ['utf-8', 'windows-1250', 'iso-8859-2']
    for enc in encodings:
        try:
            parser = etree.XMLParser(encoding=enc, recover=True)
            return etree.parse(file_path, parser)
        except (etree.XMLSyntaxError, UnicodeDecodeError):
            continue
    # Last resort: let lxml auto-detect
    parser = etree.XMLParser(recover=True)
    return etree.parse(file_path, parser)


def parse_header(header_path: str) -> dict:
    """
    Parse a PPC header.xml file.

    Returns a dict with:
        date: str (YYYY-MM-DD)
        sitting: int
        day: int
        speakers: dict {xml_id: {"name": str, "role": str, "is_chair": bool}}
    """
    tree = _parse_xml(header_path)
    root = tree.getroot()

    # --- Date and sitting metadata from sourceDesc ---
    # Navigate: teiHeader → profileDesc → settingDesc or fileDesc → sourceDesc
    date = ""
    sitting = 0
    day = 0

    # Try to find <date> anywhere in the header
    for date_el in _find_all(root, "date"):
        val = _text(date_el).strip()
        if re.match(r"\d{4}-\d{2}-\d{2}", val):
            date = val
            break

    # Try to find sessionNo, dayNo anywhere in the header
    for el in _find_all(root, "sessionNo"):
        try:
            sitting = int(_text(el))
            break
        except ValueError:
            pass
    for el in _find_all(root, "dayNo"):
        try:
            day = int(_text(el))
            break
        except ValueError:
            pass

    # --- Fallback: parse sitting/day from directory name ---
    # Directory names look like: 202327-snt-ppxxx-00001-01
    dirname = os.path.basename(os.path.dirname(header_path))
    if sitting == 0:
        match = re.search(r"-(\d{5})-", dirname)
        if match:
            sitting = int(match.group(1))
    if day == 0:
        match = re.search(r"-(\d{2})$", dirname)
        if match:
            day = int(match.group(1))

    # --- Speaker list from particDesc ---
    speakers = {}

    # Find all <person> elements
    for person_el in _find_all(root, "person"):
        xml_id = person_el.get("{http://www.w3.org/XML/1998/namespace}id", "")
        if not xml_id:
            xml_id = person_el.get("id", "")
        if not xml_id:
            continue

        # Skip the commentator pseudo-person
        if xml_id == "komentarz":
            continue

        forename = ""
        surname = ""
        role_name = ""

        for pn in _find_all_in(person_el, "persName"):
            for child in _find_all_in(pn, "forename"):
                forename = _text(child)
                break
            for child in _find_all_in(pn, "surname"):
                surname = _text(child)
                break
            for child in _find_all_in(pn, "roleName"):
                role_name = _text(child)
                break

        full_name = f"{forename} {surname}".strip()
        is_chair = role_name in CHAIR_ROLES

        speakers[xml_id] = {
            "name": full_name,
            "role": role_name,
            "is_chair": is_chair,
        }

    return {
        "date": date,
        "sitting": sitting,
        "day": day,
        "speakers": speakers,
    }


def parse_utterances(text_path: str) -> list[dict]:
    """
    Parse a PPC text_structure.xml file and return a list of utterance dicts.

    Each dict has: xml_id, who, text
    Excludes utterances with who="#komentarz".
    """
    tree = _parse_xml(text_path)
    root = tree.getroot()

    utterances = []

    # Find all <u> elements anywhere in the document
    for u_el in _find_all(root, "u"):
        xml_id = u_el.get("{http://www.w3.org/XML/1998/namespace}id", "")
        who = u_el.get("who", "")

        # Strip leading '#' from who reference
        if who.startswith("#"):
            who = who[1:]

        # Skip komentarz (procedural notes: applause, gavel, etc.)
        if who == "komentarz":
            continue

        text = _text(u_el).strip()

        # Skip empty utterances
        if not text:
            continue

        utterances.append({
            "xml_id": xml_id,
            "who": who,
            "text": text,
        })

    return utterances


# ---------------------------------------------------------------------------
# Speech ID generation
# ---------------------------------------------------------------------------

class SpeechIdGenerator:
    """Generates ParlText speech IDs (PL_S_YYYYMMDD_NNNNN) with per-date counters."""

    def __init__(self):
        self._counters: dict[str, int] = {}

    def next(self, date_str: str) -> str:
        """Return the next speech_id for the given date (YYYY-MM-DD)."""
        date_compact = date_str.replace("-", "")
        self._counters[date_str] = self._counters.get(date_str, 0) + 1
        return f"PL_S_{date_compact}_{self._counters[date_str]:05d}"

    @property
    def total(self) -> int:
        return sum(self._counters.values())

    @property
    def counters(self) -> dict[str, int]:
        """Read-only view of per-date counters."""
        return dict(self._counters)


# ---------------------------------------------------------------------------
# Link construction
# ---------------------------------------------------------------------------

def build_link(sitting: int, senate_term: int) -> str:
    """
    Construct a link URL for a Senate speech.

    The Senate does not provide per-speech URLs like the Sejm does.
    We link to the sitting-level page on senat.gov.pl.
    """
    return (
        f"https://www.senat.gov.pl/prace/posiedzenia/"
        f"przebieg,{sitting},{senate_term}.html"
    )


def _detect_cycle(input_dir: str) -> tuple[str, int]:
    """
    Detect the electoral cycle and Senate term number from the input path.

    E.g. "ppc_2015_2019_tei/2015-2019/senat/..." → ("2015-2019", 9)
    """
    # Look for a year-range pattern anywhere in the path
    match = re.search(r"(\d{4})-(\d{4})", input_dir)
    if match:
        year_range = f"{match.group(1)}-{match.group(2)}"
        term = SENATE_TERM_BY_YEARS.get(year_range, 0)
        if term == 0:
            log.error("Unrecognized year range '%s'. Known ranges: %s",
                       year_range, sorted(SENATE_TERM_BY_YEARS.keys()))
            sys.exit(1)
        return year_range, term
    log.error("Cannot detect year range from path: %s", input_dir)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert(input_dir: str, output_file: str, dry_run: bool = False) -> dict:
    """
    Main conversion: iterate PPC Senate sitting directories, parse TEI,
    write ParlText CSV.
    """
    if not os.path.isdir(input_dir):
        log.error("Input directory not found: %s", input_dir)
        sys.exit(1)

    electoral_cycle, senate_term = _detect_cycle(input_dir)
    log.info("Detected electoral cycle: %s (Senate term %d)", electoral_cycle, senate_term)

    # Get sorted list of sitting subdirectories
    sitting_dirs = sorted(
        d for d in os.listdir(input_dir)
        if os.path.isdir(os.path.join(input_dir, d))
    )
    if not sitting_dirs:
        log.error("No sitting directories found in %s", input_dir)
        sys.exit(1)

    log.info("Found %d sitting directories", len(sitting_dirs))

    if dry_run:
        for sd in sitting_dirs:
            header_path = os.path.join(input_dir, sd, "header.xml")
            if os.path.exists(header_path):
                meta = parse_header(header_path)
                log.info(
                    "  %s: %s (sitting %d, day %d), %d speakers",
                    sd, meta["date"], meta["sitting"],
                    meta["day"], len(meta["speakers"]),
                )
        log.info("Dry run complete — no data written")
        return {}

    stats = {
        "speeches_written": 0,
        "utterances_total": 0,
        "days_processed": 0,
        "missing_header": 0,
        "missing_text": 0,
        "missing_speaker": 0,
    }

    id_gen = SpeechIdGenerator()
    first_file = not os.path.exists(output_file) or os.path.getsize(output_file) == 0

    with open(output_file, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, quoting=csv.QUOTE_ALL)
        if first_file:
            writer.writeheader()

        for sd in sitting_dirs:
            sd_path = os.path.join(input_dir, sd)
            header_path = os.path.join(sd_path, "header.xml")
            text_path = os.path.join(sd_path, "text_structure.xml")

            if not os.path.exists(header_path):
                log.warning("Missing header.xml for %s — skipping", sd)
                stats["missing_header"] += 1
                continue

            if not os.path.exists(text_path):
                log.warning("Missing text_structure.xml for %s — skipping", sd)
                stats["missing_text"] += 1
                continue

            # Parse header
            meta = parse_header(header_path)
            date_str = meta["date"]
            if not date_str:
                log.warning("No date found in header for %s — skipping", sd)
                continue

            sitting = meta["sitting"]
            day = meta["day"]
            speakers = meta["speakers"]

            log.info("  %s: %s (sitting %d, day %d)", sd, date_str, sitting, day)

            # Parse utterances
            utterances = parse_utterances(text_path)
            stats["utterances_total"] += len(utterances)

            # Convert each utterance to a CSV row
            for i, utt in enumerate(utterances):
                who_id = utt["who"]

                if who_id not in speakers:
                    # Unknown speaker — use the raw ID as name
                    log.debug(
                        "    Speaker '%s' not in header for %s",
                        who_id, sd,
                    )
                    speaker_name = who_id
                    is_chair = False
                    stats["missing_speaker"] += 1
                else:
                    sp = speakers[who_id]
                    is_chair = sp["is_chair"]
                    # Standardize chair name to "Marszałek" (matching ParlText convention)
                    speaker_name = "Marszałek" if is_chair else sp["name"]

                speech_id = id_gen.next(date_str)
                speechnumber = id_gen.counters[date_str]

                link = build_link(sitting, senate_term)

                row = {
                    "speech_id": speech_id,
                    "link": link,
                    "agenda_item": "9999",
                    "electoral_cycle": electoral_cycle,
                    "speechnumber": speechnumber,
                    "speaker": speaker_name,
                    "chair": 1 if is_chair else 0,
                    "date": date_str,
                    "speech_text": utt["text"],
                    "bill_id": "9999",
                    "prediction": 999,
                    "prediction_name": "No Policy Content",
                }

                writer.writerow(row)
                stats["speeches_written"] += 1

            f.flush()
            stats["days_processed"] += 1

    log.info("=" * 60)
    log.info("CONVERSION COMPLETE")
    log.info("  Days processed:      %d", stats["days_processed"])
    log.info("  Utterances total:    %d", stats["utterances_total"])
    log.info("  Speeches written:    %d", stats["speeches_written"])
    log.info("  Missing speakers:    %d", stats["missing_speaker"])
    log.info("  Missing headers:     %d", stats["missing_header"])
    log.info("  Missing text files:  %d", stats["missing_text"])
    log.info("  Output: %s", output_file)

    # Quick validation: check for duplicate speech_ids
    speech_ids_seen: set[str] = set()
    duplicates = 0
    with open(output_file, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row.get("speech_id", "")
            if sid in speech_ids_seen:
                duplicates += 1
            speech_ids_seen.add(sid)

    log.info("  Duplicate speech_ids: %d", duplicates)
    if duplicates > 0:
        log.warning("  ⚠ Duplicate speech_ids detected — review output!")

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert PPC Senate TEI XML to ParlText CSV"
    )
    parser.add_argument(
        "--input-dir", type=str, default=DEFAULT_INPUT_DIR,
        help=f"Directory containing PPC Senate sitting subdirectories (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output", type=str, default=DEFAULT_OUTPUT_FILE,
        help=f"Output CSV file (default: {DEFAULT_OUTPUT_FILE})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List sittings and metadata without writing CSV",
    )
    args = parser.parse_args()

    convert(args.input_dir, args.output, args.dry_run)


if __name__ == "__main__":
    main()
