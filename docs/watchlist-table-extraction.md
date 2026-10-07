# Structured watchlist table extraction

Implemented narrow extraction fix; not deployed by this change. Existing Lookout triggers, literal instruction vocabulary, FORMING, sound, polling and date filters are unchanged. Migration 0016 already represents all fields; no migration or historical backfill is required.

## October 6 root cause and traced boundary

The actual user-supplied 3000 × 3800 October 6 image is checked in as `tests/fixtures/daily-watchlist-2026-10-06.png`. Its captured English Tesseract TSV is retained in `watchlist-2026-10-06-ocr.json`, without invented expected OCR readings.

1. `watchlist_image.extract_image_tokens` produces word text/confidence and bounding boxes with Tesseract `--psm 11 tsv`. Sparse OCR reads News, Support/Pivot and Game/Plan but misses Resistance.
2. The existing header-only color-normalized `--psm 6` retry crops y=202…327 for this image. It reads **Resistance correctly at 75.530922 confidence**, plus a separate Pivot at 96.178215. The previous acceptance gate required every exact heading to reach 80. It discarded the complete retry. `image_column_boundaries` independently imposed the same 80 threshold.
3. The image has a blank Symbol heading. Consequently the alternative complete six-heading detector also fails. Boundaries become `None`, and `extract_cells` emits “Table columns unavailable; only literal price instructions can be monitored.” All structured columns are unavailable.
4. Symbol discovery does not depend on those headings: `extract_watchlist_rows` finds a repeated left-hand ticker X anchor, groups stacked tickers, and retains spatial row OCR as Original Note. Active-equity validation remains mandatory. That explains why symbols/raw notes survived the column failure.
5. After geometry succeeds, tokens are assigned by their center X to ordered physical cells. Strict pivot parsing and per-cell confidence checks run independently. `ImportService.process_snapshot` validates rows; `Store._symbols` stores each row's fields/raw note in `WatchlistSymbol.structured_rows` and derives existing level instructions. The existing private upload-status API returns those structured rows for review. No public OCR diagnostic endpoint is added.

This reproduces the failure on the supplied source, not an assertion about the exact production TSV or existing production records. No production connection was available or used.

## Header and column geometry

Headings must be above the first stock row, in one nearby visual band, ordered News → Support → Resistance → Game. Split Pivot/Plan tokens are allowed. Header lettering is normalized for case/punctuation only. Support/Resistance can have one substituted letter at confidence ≥80 **only with a high-confidence Pivot directly underneath**. An exact Support/Resistance at confidence ≥70 also requires that independent Pivot. Short headings still require exact readings at ≥80. No fuzzy matching applies to symbols, prices, News or Game Plan.

The colored header's observed continuous dark rules locate the blank Symbol cell, News, two pivot columns, a narrow intervening MTF cell and Game Plan. Exactly one separator must occur in each pivot gap and two must enclose the narrow MTF gap. Ambiguous/missing borders fail closed. Coordinates come from tokens and actual image pixels, not an absolute screenshot template. Header retry acceptance now uses this corroborated geometry instead of requiring every name at ≥80. The measured October 6 starts are 0, 209, 1051.5, 1304.5, 1567.5, 1632.5; these are diagnostic measurements, not code constants.

MTF remains Unknown unless its own heading and cell mark are confidently recognized. The October 6 header OCR reads the vertical M as “™”, so it correctly stays Unknown even where an X is visible. Nearby Game Plan text never supplies MTF.

## Rows, wrapping and field safety

Printed horizontal rules enclosing the symbol row determine Y limits, using multiple column-interior samples rather than vertical borders or text. This captures wrapped News/Game Plan lines and excludes inter-row headline bands. Without usable enclosing rules, non-overlapping midpoints between neighboring symbol groups provide the existing conservative geometry fallback. Stacked SPY/QQQ symbols share one row; active-asset validation and left-column geometry prevent section prose from becoming stock symbols. Known annotation tokens are excluded before row grouping.

Within a cell, words are clustered by visual line and ordered left to right. Body/price confidence remains ≥80. Boundary-spanning, malformed or uncertain cells keep raw OCR and a review warning but cannot produce conditions. A high-confidence independent pivot pass may replace an identical low-confidence sparse token at the same position; conflicting readings still disable that cell. No price corrections or magnitude-based Support/Resistance inference occur.

Separate physical pivot borders are required on each row. Game Plan also requires its physical left border, preventing a merged prose row from presenting a truncated instruction as a complete Game Plan. News needs its right divider; this image's colored Symbol/News junction has no black rule, so requiring one would incorrectly erase valid News. Shared cells spanning multiple stock rows remain an OCR limitation: review the source rather than assuming every row owns a complete shared headline.

An extracted empty text cell is `""` and displays **Blank**; unavailable/uncertain text is `null` and displays **Unavailable**. On image imports, missing OCR is called Blank only when the inset cell interior is visibly uniform (each RGB channel range ≤40); otherwise a missing-text warning requires image review. Empty verified pivot cells use an empty `support_cell`/`resistance_cell`, empty level arrays and Blank; failures retain null/raw cell text with warnings and Unavailable. Unknown MTF is distinct from false. All these values fit existing nullable fields/JSON. Optional field uncertainty never deletes a validated row or erases its other valid cells.

Flattened Original Note remains secondary raw evidence. Its numbers are **not authoritative Support/Resistance**: numeric news, EMA references, magnet levels and Game Plan prices cannot manufacture physical pivot cells. Existing literal-only fallback remains unchanged when columns are unavailable.

Review stays upload → process → review → explicit Confirm & Activate. No auto-activation or rewrite of activated uploads occurs. The review shows Symbol, News, Support, Resistance, MTF, Game Plan, warnings and Original Note before activation.

## Development diagnostics

From the repository root, with English Tesseract and the existing Pillow dependency installed:

```sh
python tools/inspect_watchlist_geometry.py tests/fixtures/daily-watchlist-2026-10-06.png > data/watchlist-geometry.json
# Inspect a saved sparse TSV instead of rerunning the full-image/header OCR:
python tools/inspect_watchlist_geometry.py tests/fixtures/daily-watchlist-2026-10-06.png --tsv data/extraction-2026-10-06/sparse.tsv > data/sparse-geometry.json
```

The tool reports header words/coordinates/confidence, column starts, all supplied-image tokens, row bounds, fields and warnings. Saved-TSV mode can still run bounded pivot OCR if geometry succeeds. It accesses no database/provider/credentials and adds no normal UI/API diagnostics. Reports contain private source OCR: retain locally, not in public logs. `data/extraction-2026-10-06/` holds ignored investigation/test artifacts for this run.

## Deployment and verification (operator steps only)

Final local verification: **267/267 backend tests passed on disposable PostgreSQL**, including real September 21/October 6 OCR and migrations through 0016. SQLite ran 267 tests successfully with five expected skips (three real-Tesseract tests and two PostgreSQL-only concurrency checks). The focused extraction/adapter suite ran 36 tests successfully with two local Tesseract skips. Public browser tests passed 19/19; private browser tests passed 15/15, including structured staged-review assertions. Both production builds and Prettier checks, Python compileall, Alembic heads (0016), and git diff --check passed. Manual physical-border probes on half-size and double-size source images also succeeded.

The final actual-image diagnostic found 34 candidate rows; provider validation still applies before activation. MSFT's 529/528 and 531, AMD's 642/640 and 646.5/647, and AMD's wrapped News are recovered. Support OCR for APLD, VKTX and CRWD remains below the required confidence and is unavailable with warnings; their valid Resistance/Game Plan fields survive. The vertical MTF heading remains uncertain. Shared headlines spanning multiple stock rows may produce partial row-associated News; inspect the source image. OCR wording errors such as AI→Al are retained, never silently corrected. No production upload/database was inspected or repaired.

Files changed:

- Extraction: `ripster_scanner/watchlist.py`, `watchlist_image.py`, `watchlist_table.py`.
- Private staged review: `strategy-lab-frontend/src/DailyWatchlist.jsx`, `strategy-lab-frontend/tests/replay.spec.js`.
- Tests/diagnostics: `tests/test_watchlist_table.py`, `tests/fixtures/daily-watchlist-2026-10-06.png`, `tests/fixtures/watchlist-2026-10-06-ocr.json`, `tools/inspect_watchlist_geometry.py`.
- Documentation: `README.md`, `docs/frontend.md`, `docs/watchlist-lookout-alerts.md`, this document, `tools/README.md`.

No deployment was performed. Review and release this code through the existing image workflow described in [deployment.md](deployment.md); require all tests/builds and verified amd64/arm64 manifests. Use a new immutable `sha-XXXXXXX` release. Production is already at 0016: **do not edit 0016, run a new migration, backfill, or manually repair its October 6 upload**. Keep the previous images for rollback.

For a separately authorized local Compose deployment, the exact application commands are:

```sh
docker compose build backend strategy-lab
docker compose up -d --no-deps backend internal-backend scanner research strategy-lab
docker compose exec -T backend python -m alembic heads
docker compose exec -T backend python -m alembic current
```

For the actual production installation, the operator uses the existing separate deployment repository to pin the shared application and private Strategy Lab image to the verified release; this repository cannot supply uninspected cluster-resource commands. No public frontend change is required. Normal migration-version checks must still show 0016/head; no schema update is part of this fix.

After deployment:

1. Verify health and private Daily Watchlist review availability. Confirm existing activated uploads/history are unchanged.
2. Intentionally upload a **new** copy of the source image; do not mutate/reprocess the existing activated October 6 record. New uploads retain the existing New York ingestion trading date. A later-day upload is not a backdated October 6 alert replay.
3. Before activation, compare source/review: MSFT Support 529/528, Resistance 531, Game Plan ending “No Go under 528”; AMD Support 642/640, Resistance 646.5/647 and wrapped News; AMZN Support 252/252.50, Resistance 254. Verify section headlines are not stocks and SPY/QQQ have no pivot levels/partial Game Plan.
4. Inspect every warning against the screenshot. MTF may legitimately be Unknown; any unusable cell must remain unavailable. Source oddities such as XNDU Resistance 4.9/50 and GFS Support 49.14 versus Resistance 40.40 must not be silently corrected.
5. Only after human verification, intentionally confirm activation if appropriate for that day's watchlist. Verify existing monitors read-only against reviewed structured levels. Do not inject fake prices, fabricate earlier crossings, or expect historical alerts to be reconstructed.
6. Confirm existing live Alerts/date filters, 15-second refresh and optional sound still behave normally, with FORMING research persistence unchanged.
