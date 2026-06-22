# Poland Parliamentary Corpus

Extending the [ParlText CEE](https://parltext.org/repository/) dataset of Polish parliamentary speeches to cover **both chambers** (Sejm and Senat) from 1991 onwards.

## Background

The ParlText CEE project compiled a comprehensive database of parliamentary speeches, bills, and laws for Central-Eastern European countries. The Polish speech corpus (`PL_speeches.csv`) contains **717,809 speeches** spanning **1991-11-25 to 2023-08-30**, sourced from the official Sejm archives. ParlText covers only the Sejm (lower house) by design.

This repository extends the dataset in two dimensions:
1. **Sejm 2023+**: 34,602 speeches from the 10th term, scraped via the official [Sejm REST API](https://api.sejm.gov.pl)
2. **Senat 2015+**: 443,854 speeches from the 9th, 10th, and 11th terms (and expanding), converted from the [Polish Parliamentary Corpus](https://clip.ipipan.waw.pl/PPC) (PPC) TEI XML data (Ogrodniczuk et al.)

## Obtaining the Base Dataset (`PL_speeches.csv`)

The original ParlText CEE Polish speech corpus is **not included in this repository** due to its size (1.3 GB, 717,809 rows). It must be obtained separately from the official source:

| Detail | Value |
|--------|-------|
| **File** | `PL_speeches.csv` |
| **Download** | [Harvard Dataverse — ParlText CEE](https://dataverse.harvard.edu/dataverse/parltext) |
| **License** | CC BY-NC 4.0 (Attribution-NonCommercial) |
| **Direct download** | `PL_speeches.csv` is listed under the Poland section of the Dataverse repository |
| **Codebook** | The `codebook_ParlText_PL_speeches.pdf` file in this repository documents the schema |
| **Coverage** | Sejm (lower house only): 1991-11-25 to 2023-08-30, 1st–9th terms |
| **Size** | ~1.3 GB, 717,809 speeches |

**How the datasets fit together:**

```
PL_speeches.csv                     ← ParlText CEE base (Sejm 1991–2023), from Harvard Dataverse
    +
PL_speeches_2023_onwards.csv        ← Our Sejm extension (2023–2026), from Sejm API
    +
PL_speeches_senat_all.csv           ← Our Senat addition (2015–2025), from PPC TEI
    =
Complete bicameral Polish corpus (1991–2025)
```

Place `PL_speeches.csv` in this directory alongside the other CSV files to create the full dataset. All files share the same 12-column schema (the Senat file adds a `house` column to distinguish chambers).

## Repository Structure

```
poland-parliamentary-corpus/
├── README.md                          # This file
├── IMPLEMENTATION_PLAN.md             # Detailed methodology and implementation plan
├── scraper.py                         # Python scraper for the Sejm API
├── convert_ppc_senate_to_parltext.py  # PPC Senate TEI → ParlText CSV converter
├── requirements.txt                   # Python dependencies
├── .gitignore                         # Ignores ZIPs, extracted data, generated CSVs
│
├── PL_speeches.csv                    # ★ Obtain from Harvard Dataverse (not in repo)
├── PL_speeches_2023_onwards.csv       # Output: Sejm 2023+ dataset
├── PL_speeches_senat_*.csv            # Output: Senat term datasets (2015+)
├── PL_speeches_senat_all.csv          # Output: All Senat terms merged (with house col)
│
└── codebook_ParlText_PL_speeches.pdf  # Original ParlText codebook
```

## Final Dataset Statistics

### Sejm (Lower House) — 10th Term

| Metric | Count |
|--------|-------|
| **Speeches** | 34,602 |
| **Sittings** | 61 (all from 10th term) |
| **Sitting days** | 152 |
| **Date range** | 2023-11-13 to 2026-06-18 |
| **Unique speakers** | 615 |
| **Chair speeches** | 153 (0.4%) |
| **Electoral cycle** | 2023-2027 |
| **Speech length (mean)** | 2,426 chars |
| **Empty values** | 0 |
| **Duplicate IDs** | 0 |

### Senat (Upper House) — 9th, 10th & 11th Terms

#### Combined

| Metric | Count |
|--------|-------|
| **Total speeches** | 443,854 |
| **Terms covered** | 3 (9th, 10th, 11th) |
| **Date range** | 2015-11-12 to 2025-04-24 |
| **File** | `PL_speeches_senat_all.csv` (192 MB) |

#### By Term

| Term | Electoral Cycle | Speeches | Dates | Speakers | Chair % | File |
|------|-----------------|----------|-------|----------|---------|------|
| 9th | 2015–2019 | 221,112 | 204 | 322 | 43.4% | `PL_speeches_senat_2015_2019.csv` |
| 10th | 2019–2023 | 186,450 | 147 | 392 | 37.0% | `PL_speeches_senat_2019_2023.csv` |
| 11th | 2023–2027 | 36,292 | 53 | 225 | 47.5% | `PL_speeches_senat_2023_onwards.csv` |

> **Note on chair percentage**: The Senat chair percentage (37–48%) is much higher than the Sejm (0.4%) because Senate plenary sessions are smaller (100 senators vs. 460 deputies) and the presiding officer (Marszałek Senatu / Wicemarszałek Senatu) manages nearly every speaker transition. This is a structural feature of the Senate, not a data artifact.

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

## Data Sources

### Sejm
Speech data is obtained from the official [Sejm REST API](https://api.sejm.gov.pl):

- `GET /sejm/term10/proceedings` — list of sittings
- `GET /sejm/term10/proceedings/{sitting}/{date}/transcripts` — speech metadata
- `GET /sejm/term10/proceedings/{sitting}/{date}/transcripts/{id}` — full speech text

### Senat
The Polish Senate does not provide a public API like the Sejm. Instead, Senate speech data is sourced from the **[Polish Parliamentary Corpus](https://clip.ipipan.waw.pl/PPC)** (PPC) maintained by the Institute of Computer Science, Polish Academy of Sciences (Ogrodniczuk et al., 2012–2025).

The PPC provides Senate stenographic records in **TEI P5 XML** format, segmented into individual utterances with speaker metadata. Our converter (`convert_ppc_senate_to_parltext.py`) harmonizes this TEI data into the ParlText CSV schema.

**PPC Senate data sources**:
- [2015–2019 TEI](https://kdp.ipipan.waw.pl/static/ppcdump-tei/2015-2019-tei.zip) — Senate 9th term
- [2019–2023 TEI](https://kdp.ipipan.waw.pl/static/ppcdump-tei/2019-2023-tei.zip) — Senate 10th term
- [2023–2027 TEI](https://kdp.ipipan.waw.pl/static/ppcdump-tei/2023-2027-tei.zip) — Senate 11th term

**Key conversion steps**:
1. Parse `header.xml` for metadata (date, sitting, speaker list with roles)
2. Parse `text_structure.xml` for individual `<u>` utterances
3. Filter procedural markers (`who="#komentarz"`)
4. Resolve speaker references → human-readable names
5. Detect chair via `<roleName>` match on `Marszałek` / `Wicemarszałek` / `Marszałek Senior`
6. Auto-detect electoral cycle and Senate term number from directory path
7. Generate ParlText speech IDs (`PL_S_YYYYMMDD_NNNNN`) with per-date counters

## Usage

```bash
# Sejm scraper (with checkpoint/resume support)
python scraper.py
python scraper.py --resume
python scraper.py --sitting 1 --date 2023-11-13 --output my_output.csv
python scraper.py --dry-run

# Senat PPC converter
python convert_ppc_senate_to_parltext.py
python convert_ppc_senate_to_parltext.py --dry-run
python convert_ppc_senate_to_parltext.py --input-dir path/to/ppc/data --output my_output.csv
```

## Known Limitations

- **Agenda items**: Set to `"9999"` (agenda-to-speech matching not yet implemented)
- **Bill IDs**: Set to `"9999"` (bill linkage requires separate database)
- **CAP topic coding**: Set to `999` / `"No Policy Content"` (ML classifier not yet built)
- **Senat source**: Dependent on PPC update cadence (not real-time scraping). Latest PPC data: 2025-04-24.
- **Senat links**: Senate does not provide per-speech URLs; `link` field points to sitting-level page on senat.gov.pl.
- **Pre-2015 Senat**: PPC has Senate data back to 1922 (and 1989–2015 for the reinstated Senate). Not yet converted — available for future expansion.

## References

- [ParlText CEE Repository](https://parltext.org/repository/)
- [ParlText Dataverse (Harvard)](https://dataverse.harvard.edu/dataverse/parltext)
- [Sejm Open Data API](https://api.sejm.gov.pl)
- [Polish Parliamentary Corpus (PPC)](https://clip.ipipan.waw.pl/PPC)
- Ogrodniczuk, M. (2018). "Polish Parliamentary Corpus." *ParlaCLARIN 2018.*
- Ogrodniczuk, M. & Nitoń, B. (2020). "New developments in the Polish Parliamentary Corpus." *ParlaCLARIN II.*
- Sebők, M., Molnár, C., & Takács, A. (2025). "Levelling up quantitative legislative studies on Central-Eastern Europe." *Intersections: EEJSP.*
