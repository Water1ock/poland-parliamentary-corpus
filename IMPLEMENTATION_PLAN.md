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

### 3.3 Term Coverage via API

- **Term 9**: `GET /sejm/term9/proceedings` → 81 sittings (all already in PL_speeches.csv)
- **Term 10**: `GET /sejm/term10/proceedings` → currently ~75 sittings (ongoing)

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
- [ ] Confirm all three endpoint tiers work for term 10
- [ ] Verify transcript HTML structure for term 10
- [ ] Test URL construction for `link` field

### Step 2: Build Core Scraper (`scraper.py`)
- [ ] `fetch_proceedings(term)` — get sitting list
- [ ] `fetch_transcripts_list(sitting, date)` — get statement metadata
- [ ] `fetch_speech_html(sitting, date, speech_id)` — get individual speech
- [ ] `parse_speech_html(html)` — extract clean speech text
- [ ] `build_csv_row(...)` — assemble all fields

### Step 3: Run for 10th Term
- [ ] Iterate all sittings from proceeding 1 onwards
- [ ] For each sitting day, fetch all speeches
- [ ] Write incrementally to CSV (append mode)

### Step 4: Validate Output
- [ ] Verify row count, column count
- [ ] Check no duplicate `speech_id` values
- [ ] Spot-check speech content against live Sejm website
- [ ] Compare format against `PL_speeches.csv` sample

### Step 5: Document
- [ ] Update README with usage instructions
- [ ] Document any deviations from original methodology
- [ ] Note placeholder values and future improvements

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
