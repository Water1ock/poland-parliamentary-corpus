# Poland Parliamentary Corpus

Extending the [ParlText CEE](https://parltext.org/repository/) dataset of Polish parliamentary speeches (Sejm) from 2023 onwards.

## Background

The ParlText CEE project compiled a comprehensive database of parliamentary speeches, bills, and laws for Central-Eastern European countries. The Polish speech corpus (`PL_speeches.csv`) contains **717,809 speeches** spanning **1991-11-25 to 2023-08-30**, sourced from the official Sejm archives.

This repository extends that dataset, covering the **10th term of the Sejm** (2023-2027) using the official [Sejm REST API](https://api.sejm.gov.pl). The scrape is **complete** — 34,602 speeches from November 13, 2023 through June 18, 2026.

## Repository Structure

```
poland-parliamentary-corpus/
├── README.md                          # This file
├── IMPLEMENTATION_PLAN.md             # Detailed methodology and implementation plan
├── scraper.py                         # Python scraper for the Sejm API
├── .gitignore                         # Ignores build artifacts, logs, checkpoints
├── PL_speeches_2023_onwards.csv       # Output: extended dataset (2023 onwards)
└── codebook_ParlText_PL_speeches.pdf  # Original codebook (source data in parent dir)
```

## Final Dataset Statistics

| Metric | Count |
|--------|-------|
| **Speeches** | 34,602 |
| **Sittings** | 61 (all from 10th term) |
| **Sitting days** | 152 |
| **Date range** | 2023-11-13 to 2026-06-18 |
| **Unique speakers** | 615 |
| **Chair speeches** | 153 |
| **Electoral cycle** | 2023-2027 |
| **Speech length (mean)** | 2,426 chars |
| **Empty values** | 0 (all columns fully populated) |
| **Duplicate IDs** | 0 |

## Dataset Format

The output CSV matches the original `PL_speeches.csv` format:

| Column | Description |
|--------|-------------|
| `speech_id` | Unique ID: `PL_S_YYYYMMDD_NNNNN` |
| `link` | URL to original speech source |
| `agenda_item` | Agenda item code (`"9999"` if not available) |
| `electoral_cycle` | Parliamentary term (e.g., `"2023-2027"`) |
| `speechnumber` | Running order within the date |
| `speaker` | Speaker name (standardized `"Marszałek"` for chair) |
| `chair` | `1` if presiding officer, `0` otherwise |
| `date` | Speech date (`YYYY-MM-DD`) |
| `speech_text` | Full speech text |
| `bill_id` | Associated bill ID (`"9999"` if not available) |
| `prediction` | CAP topic code (`999` = not coded) |
| `prediction_name` | CAP topic name (`"No Policy Content"` when not coded) |

## Data Source

Speech data is obtained from the official [Sejm REST API](https://api.sejm.gov.pl):

- `GET /sejm/term10/proceedings` — list of sittings
- `GET /sejm/term10/proceedings/{sitting}/{date}/transcripts` — speech metadata
- `GET /sejm/term10/proceedings/{sitting}/{date}/transcripts/{id}` — full speech text

## Usage

```bash
# Run the scraper (with checkpoint/resume support)
python scraper.py

# Resume after interruption
python scraper.py --resume

# Scrape a specific sitting
python scraper.py --sitting 1 --date 2023-11-13 --output my_output.csv

# Dry-run to see what would be scraped
python scraper.py --dry-run
```

## Known Limitations

- **Agenda items**: Set to `"9999"` (agenda-to-speech matching not yet implemented)
- **Bill IDs**: Set to `"9999"` (bill linkage requires separate database)
- **CAP topic coding**: Set to `999` / `"No Policy Content"` (ML classifier not yet built)

## References

- [ParlText CEE Repository](https://parltext.org/repository/)
- [ParlText Dataverse (Harvard)](https://dataverse.harvard.edu/dataverse/parltext)
- [Sejm Open Data API](https://api.sejm.gov.pl)
- Sebők, M., Molnár, C., & Takács, A. (2025). "Levelling up quantitative legislative studies on Central-Eastern Europe." *Intersections: EEJSP.*
