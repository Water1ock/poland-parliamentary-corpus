# Implementation Plan: Extending PL_speeches (2023 Onwards)

## 1. Project Overview

**Goal**: Replicate the ParlText CEE methodology to extend the Polish parliamentary speeches dataset (`PL_speeches.csv`) from September 2023 onwards, producing `PL_speeches_2023_onwards.csv`.

**Source dataset**: `PL_speeches.csv` — 717,809 speeches from the Polish Sejm, spanning 1991-11-25 to 2023-08-30, originally compiled by the ParlText project (Sebők, Molnár & Takács, 2025).

**GitHub**: [github.com/Water1ock/poland-parliamentary-corpus](https://github.com/Water1ock/poland-parliamentary-corpus)

## 2. The Gap

| Period | Term | Status |
|--------|------|--------|
| 1991-11-25 to 2023-08-30 | 1st–9th | ✅ In `PL_speeches.csv` |
| 2023-08-31 to 2023-11-12 | 9th (ended) | ❌ No sittings — gap between terms |
| 2023-11-13 onwards | 10th | ❌ Not scraped yet |

**Key finding**: The 9th term held its final sitting (#81) on Aug 16, 17, and 30, 2023. All three days ARE in the existing dataset. No further 9th term sittings occurred. The 10th term commenced on Nov 13, 2023.

## 3. Data Source: Sejm REST API

### 3.1 Why the API (not HTML scraping)?

The ParlText project used custom HTML scrapers for the legacy `orka2.sejm.gov.pl` Domino-based archives. However, for the 10th term (and late 9th term), the Sejm now provides a REST API at `api.sejm.gov.pl` that:

- Returns structured JSON metadata for all proceedings
- Provides **full speech text** via individual transcript endpoints
- Is the officially recommended access method
- Eliminates CAPTCHA and anti-bot protections on the HTML portal

### 3.2 API Endpoint Architecture

```
GET /sejm/term{term}/proceedings
  └─ Returns list of all sittings with dates and agenda

GET /sejm/term{term}/proceedings/{sitting}/{date}/transcripts
  └─ Returns array of statement metadata objects:
     { name, function, memberID, num, startDateTime, endDateTime,
       rapporteur, secretary, unspoken }

GET /sejm/term{term}/proceedings/{sitting}/{date}/transcripts/{id}
  └─ Returns HTML with the FULL speech text for that individual speech
```

**Critical**: The `/transcripts` list endpoint returns only metadata (speaker, timestamps). The actual speech text must be fetched one-by-one via `/transcripts/{id}`.

**Critical: WAF Protection**: The Sejm API gateway blocks requests with `Accept: application/json` on the individual transcript endpoint (which returns `text/html`). The scraper must override the session `Accept` header to `text/html, */*` before fetching individual transcripts.

### 3.3 Term Coverage via API

- **Term 9**: `GET /sejm/term9/proceedings` → 81 sittings (all already in PL_speeches.csv)
- **Term 10**: `GET /sejm/term10/proceedings` → 61 sittings (scraped)

## 4. Scraper Architecture

### 4.1 High-Level Flow

```
1. Fetch sitting list from API
2. Filter to new data (10th term only)
3. For each sitting, iterate over dates
4.   For each date, fetch transcripts list
5.     For each statement, fetch individual transcript HTML
6.       Parse HTML → extract speaker, text, chair status
7.       Write row to CSV
```

### 4.2 Field Mapping

| CSV Column | Source | Notes |
|---|---|---|
| `speech_id` | `PL_S_{YYYYMMDD}_{NNNNN}` | Running order resets daily, 5-digit zero-padded |
| `link` | Constructed Sejm URL | `https://www.sejm.gov.pl/Sejm{term}.nsf/wypowiedz.xsp?posiedzenie={sitting}&dzien={day}&wyp={index}&view=1` |
| `agenda_item` | `"9999"` | Placeholder — agenda-to-speech matching needs separate implementation |
| `electoral_cycle` | From term | `"2019-2023"` or `"2023-2027"` |
| `speechnumber` | Running counter | Resets per day (1-based), matches existing convention |
| `speaker` | `statements[i].name` | Standardized "Marszałek" for all chair persons |
| `chair` | Derived from function | `1` if function contains "Marszałek", else `0` |
| `date` | API date (ISO) | `YYYY-MM-DD` format |
| `speech_text` | Parsed from `/transcripts/{id}` HTML | Strip speaker name prefix, applause markers, HTML tags |
| `bill_id` | `"9999"` | Placeholder — bill matching needs separate implementation |
| `prediction` | `999` | Placeholder — CAP topic coding skipped for now |
| `prediction_name` | `"No Policy Content"` | Placeholder — CAP topic coding skipped for now |

### 4.3 Speech ID Convention

The existing dataset uses the format: `PL_S_YYYYMMDD_NNNNN`

- `YYYYMMDD` = date of the speech
- `NNNNN` = running order within that date, 5-digit zero-padded, starts at 1

Example: `PL_S_20230830_00001` through `PL_S_20230830_00067`

### 4.4 Chair Detection

The existing dataset standardizes all presiding officers as `"Marszałek"` in the `speaker` column, with `chair=1`. The API returns distinct functions:
- `"Marszałek Sejmu"` → chair=1, speaker="Marszałek"
- `"Wicemarszałek Sejmu"` → chair=1, speaker="Marszałek"
- `"Marszałek Senior"` → chair=1, speaker="Marszałek"

**Rule**: If `function` contains `"Marszałek"`, set `chair=1` and `speaker="Marszałek"`.

### 4.5 HTML Parsing Rules

The transcript HTML from `/transcripts/{id}` typically contains:
```html
<p class="mowca-link"><a name="001" href="001">Poseł Jan Kowalski</a></p>
<p>Treść wypowiedzi...</p>
<p>(Oklaski)</p>
```

**Parsing steps**:
1. Extract text from all `<p>` elements after the speaker header
2. Remove `(Oklaski)`, `(Głos z sali)`, `(Poruszenie na sali)` stage directions
3. Strip the speaker name prefix if present at start of text (e.g., `"Poseł Jan Kowalski:"`)
4. Normalize whitespace (collapse multiple newlines, trim)
5. Keep interjections inline as they appear in the original transcript

## 5. Identified Issues & Mitigations

### 5.1 Rate Limiting
**Risk**: Tens of thousands of sequential API calls for individual transcripts.
**Mitigation**: 
- Add `time.sleep(0.5)` between requests
- Implement exponential backoff on 429/503 responses
- Cache transcripts locally to avoid re-fetching
- Use session reuse (`requests.Session`)

### 5.2 URL Construction for 10th Term
**Risk**: The Sejm website URL format for 10th term may differ from `Sejm9.nsf/wypowiedz.xsp`.
**Mitigation**: Test the URL format against the live site before bulk scraping. The 10th term portal is at `sejm.gov.pl/sejm10.nsf/stenogramy.xsp`. If `wypowiedz.xsp` doesn't work, use the known working format or fall back to the API URL as the `link` value.

### 5.3 Running Order vs API Index
**Risk**: The API's statement `num` field may not perfectly map to the `speechnumber` we need.
**Mitigation**: Use our own sequential counter (per date) rather than relying on the API's internal numbering.

### 5.4 Polish Character Encoding
**Risk**: UTF-8 issues with Polish diacritics (ą, ć, ę, ł, ń, ó, ś, ź, ż).
**Mitigation**: 
- Always decode API responses as UTF-8
- Write CSV with `encoding='utf-8-sig'` for BOM support
- Quote all CSV fields to handle commas in text

### 5.5 Missing or Incomplete Transcripts
**Risk**: Some `/transcripts/{id}` endpoints may return 404 or empty content.
**Mitigation**: Log and skip failed fetches. Include a summary of skipped speeches in the output.

### 5.6 Agreement with Existing Format
**Risk**: Subtle differences in speech_text formatting (applause markers, interjections, speaker prefix handling).
**Mitigation**: Sample-comparison: after scraping the first sitting, visually compare with existing entries from `PL_speeches.csv` to verify formatting consistency.

## 6. Step-by-Step Implementation

### Step 1: Verify API Access
- [x] Confirm all three endpoint tiers work for term 10
- [x] Verify transcript HTML structure for term 10
- [x] Test URL construction for `link` field

### Step 2: Build Core Scraper (`scraper.py`)
- [x] `fetch_proceedings(term)` — get sitting list
- [x] `fetch_transcripts_list(sitting, date)` — get statement metadata
- [x] `fetch_speech_html(sitting, date, speech_id)` — get individual speech
- [x] `parse_speech_html(html)` — extract clean speech text
- [x] `build_csv_row(...)` — assemble all fields
- [x] Checkpoint/resume support with CSV truncation

### Step 3: Run for 10th Term
- [x] Iterate all sittings from proceeding 1 onwards
- [x] For each sitting day, fetch all speeches
- [x] Write incrementally to CSV (append mode)
- [x] Handle "unspoken" entries (oświadczenia — written statements)

### Step 4: Validate Output
- [x] Verify row count, column count
- [x] Check no duplicate `speech_id` values
- [x] Spot-check speech content against live Sejm website
- [x] Compare format against `PL_speeches.csv` sample

### Step 5: Document
- [x] Update README with usage instructions
- [x] Document any deviations from original methodology
- [x] Note placeholder values and future improvements

## 7. Actual Results

| Metric | Value |
|--------|-------|
| **Speeches** | 34,602 |
| **Sittings** | 61 (sequential, no gaps) |
| **Sitting days** | 152 |
| **Date range** | 2023-11-13 to 2026-06-18 |
| **Runtime** | 465 minutes (~7.75 hours) |
| **Unique speakers** | 615 |
| **Chair speeches** | 153 |
| **Empty cells** | 0 |
| **Duplicate IDs** | 0 |
| **Speech length (mean)** | 2,426 chars |
| **Speech length (median)** | 1,396 chars |
| **Longest speech** | 133,993 chars |

### Bugs Encountered & Fixed During Development

| Bug | Impact | Solution |
|-----|--------|----------|
| WAF blocking (Accept header mismatch) | All speech texts were error pages | Override `Accept` to `text/html` on transcript endpoints |
| Empty `function` field for chair speakers | Marszałek speeches had `chair=0` | Also check speaker name for "Marszałek" |
| Skipping `unspoken` entries | ~370 written statements lost | Include unspoken entries (oświadczenia) |
| `f.tell()` unreliable for byte offsets | CSV truncation on resume could be wrong | Use `os.path.getsize()` instead |

## 7. Limitations (Intentional)

| Aspect | Status | Rationale |
|--------|--------|-----------|
| `agenda_item` | `"9999"` | Agenda-to-speech matching is complex; can be added later |
| `bill_id` | `"9999"` | Bill linkage requires separate bill database |
| `prediction` | `999` | CAP topic coding requires ML model training |
| `prediction_name` | `"No Policy Content"` | Same as above |

## 8. References

- ParlText repository: [parltext.org/repository](https://parltext.org/repository/)
- ParlText Dataverse: [dataverse.harvard.edu/dataverse/parltext](https://dataverse.harvard.edu/dataverse/parltext)
- Sejm API: [api.sejm.gov.pl](https://api.sejm.gov.pl)
- Sejm API docs: [api.sejm.gov.pl/sejm/openapi/ui](https://api.sejm.gov.pl/sejm/openapi/ui/)
- Sebők, M., Molnár, C., & Takács, A. (2025). "Levelling up quantitative legislative studies on Central-Eastern Europe: Introducing the ParlText CEE Database." *Intersections: East European Journal of Society and Politics.*
- Comparative Agendas Project: [comparativeagendas.net](https://comparativeagendas.net/pages/master-codebook)

---

# Extension: Polish Senat (Upper House) — 11th Term

## 9. Rationale

ParlText CEE covers only the lower chambers (or unicameral legislatures) by design. The Polish Senate was excluded for cross-country comparability, not because data was unavailable. This extension fills that documented gap.

## 10. Data Source: Polish Parliamentary Corpus (PPC)

The Polish Senate does not provide a public API equivalent to `api.sejm.gov.pl`. Instead, Senate stenographic records are sourced from the **[Polish Parliamentary Corpus](https://clip.ipipan.waw.pl/PPC)** (Ogrodniczuk et al., IPI PAN), which provides Senate plenary data in **TEI P5 XML** format.

**Download**: [https://kdp.ipipan.waw.pl/static/ppcdump-tei/2023-2027-tei.zip](https://kdp.ipipan.waw.pl/static/ppcdump-tei/2023-2027-tei.zip)

**PPC data structure**:
```
2023-2027/senat/posiedzenia/pp/
├── 202327-snt-ppxxx-00001-01/    # Sitting 1, Day 1
│   ├── header.xml                # Metadata + speaker list
│   ├── text_structure.xml        # Speech utterances (TEI)
│   └── anno.ccl.gz              # Linguistic annotations (not used)
└── ...
```

**License**: Parliamentary data is public domain; PPC annotations are CC-BY.

## 11. TEI → ParlText Mapping

| ParlText Column | PPC TEI Source | Notes |
|---|---|---|
| `speech_id` | Constructed: `PL_S_{date}_{counter}` | Per-date running order |
| `link` | Constructed Senat URL | Sitting-level page (no per-speech URLs exist) |
| `agenda_item` | `"9999"` | Placeholder |
| `electoral_cycle` | `"2023-2027"` | From term 11 |
| `speechnumber` | Running counter | Resets per date |
| `speaker` | `<persName>` via `who` reference | Standardized to `"Marszałek"` for chair |
| `chair` | `<roleName>` match | `1` for `Marszałek`, `Wicemarszałek`, `Marszałek Senior` |
| `date` | `<date>` in header.xml | ISO format |
| `speech_text` | `<u>` element text content | Procedural `#komentarz` utterances filtered out |
| `bill_id` | `"9999"` | Placeholder |
| `prediction` | `999` | Placeholder |
| `prediction_name` | `"No Policy Content"` | Placeholder |

### 11.1 Chair Detection

Unlike the Sejm scraper (which uses a broad `Marszałek` substring match), the Senate converter uses exact-set matching against `{"Marszałek", "Wicemarszałek", "Marszałek Senior"}`. This correctly excludes:
- `Marszałek Sejmu RP` (visiting Sejm Marshal — not presiding over the Senate)
- `Marszałek Województwa Śląskiego` (regional voivodeship marshal)

### 11.2 Procedural Filtering

The PPC tags procedural/stage-direction notes as `<u who="#komentarz">`. These are filtered out:
- `(Oklaski)` — applause
- `(Głos z sali)` — interjections from the floor
- `(Poruszenie na sali)` — commotion
- `(Wszyscy wstają)` — everyone rises
- Opening/closing ceremony markers

### 11.3 Speaker Resolution

Speaker IDs in `<u who="#AndrzejDuda">` are cross-referenced against the `<person>` list in `header.xml` to resolve human-readable names and roles.

## 12. Converter Architecture

**Script**: `convert_ppc_senate_to_parltext.py`

```
1. Iterate sitting subdirectories (sorted)
2. For each sitting:
   a. Parse header.xml → date, sitting#, speaker list with roles
   b. Parse text_structure.xml → list of <u> utterances
   c. Filter out who="#komentarz"
   d. For each remaining utterance:
      - Resolve speaker name and chair status
      - Generate speech_id (per-date counter)
      - Write CSV row
3. Validate: check for duplicate speech_ids
```

**Usage**:
```bash
python convert_ppc_senate_to_parltext.py           # Full conversion
python convert_ppc_senate_to_parltext.py --dry-run # Preview only
```

## 13. Actual Results

### Combined (All Terms)

| Metric | Value |
|--------|-------|
| **Total speeches** | 443,854 |
| **Terms covered** | 3 (9th, 10th, 11th) |
| **Date range** | 2015-11-12 to 2025-04-24 |
| **Output** | `PL_speeches_senat_all.csv` (192 MB, with `house` column) |

### By Term

| Term | Electoral Cycle | Speeches | Days | Speakers | Chair % | Date Range |
|------|-----------------|----------|------|----------|---------|------------|
| 9th | 2015–2019 | 221,112 | 204 | 322 | 43.4% | 2015-11-12 to 2019-10-18 |
| 10th | 2019–2023 | 186,450 | 147 | 392 | 37.0% | 2019-11-12 to 2023-09-07 |
| 11th | 2023–2027 | 36,292 | 53 | 225 | 47.5% | 2023-11-13 to 2025-04-24 |

**Note on chair percentage**: The Senate chair percentage (37–48%) is dramatically higher than the Sejm (0.4%) because:
- Senate sessions are smaller (100 senators vs. 460 deputies)
- The presiding officer (Marszałek Senatu / Wicemarszałek Senatu) manages nearly every procedural transition
- Each speaker introduction, agenda item transition, and vote call is a separate utterance
- This is a structural feature of Senate proceedings, consistent with the PPC's utterance segmentation

## 14. Multi-Term Support

The converter auto-detects the electoral cycle and Senate term number from the input directory path (e.g., `2015-2019/senat/posiedzenia/pp` → cycle `"2015-2019"`, Senate term 9). This allows the same converter script to process any PPC term without manual configuration.

**Supported term mapping**:
```
1989-1991 → Senate 1st term    2007-2011 → Senate 7th term
1991-1993 → Senate 2nd term    2011-2015 → Senate 8th term
1993-1997 → Senate 3rd term    2015-2019 → Senate 9th term
1997-2001 → Senate 4th term    2019-2023 → Senate 10th term
2001-2005 → Senate 5th term    2023-2027 → Senate 11th term
2005-2007 → Senate 6th term
```

> PPC also contains pre-WWII Senate data (1922–1939, terms 1–5). These terms are not yet mapped in the converter but could be added.

## 15. Limitations

| Aspect | Status | Rationale |
|--------|--------|-----------|
| `agenda_item` | `"9999"` | Not available in PPC TEI data |
| `bill_id` | `"9999"` | Bill linkage requires separate database |
| `prediction` / `prediction_name` | Placeholders | CAP topic coding not yet implemented |
| **Data source** | Dependent on PPC updates | Not real-time scraping; relies on PPC release cadence |
| **Per-speech URLs** | Not available | Senate website provides only sitting-level pages, not per-speech links |
| **Date recency** | 2025-04-24 cutoff | PPC data may lag behind live Senate sessions |
