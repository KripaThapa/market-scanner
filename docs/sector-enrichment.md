# Sector Enrichment V1 — implemented locally

```text
FMP (classification/reference metadata only)
 ↓
SymbolMetadataProvider → SymbolMetadataService → existing symbol_metadata cache
                                                  ↓
                               frozen universe classification
                                                  ↓
                                      scanner / research / alerts
```

Alpaca/IEX remains the only scanner price/candle provider. FMP never participates
in indicators, FORMING decisions, entry context, discovery selection or ranking.
The default strategy remains `experimental-forming-v1/b067b3150de3`.

## Runtime and cache policy

`scanner.worker.main` injects `FMPMetadataProvider` when `FMP_API_KEY` is present.
The standalone worker loads the local `.env`; local Compose passes this variable
only to the scanner. Tests and directly constructed workers/services default to
cache/fallback-only operation unless a provider/service is explicitly injected.
No key means scanning continues with cached classification or UNKNOWN.

After source memberships commit, `DiscoveryService.build_universe` resolves the
entire merged universe once, before price scanning. Network requests never occur
inside the per-symbol price scan or publication transaction. Known classifications
are copied into the cycle's universe; publication copies its sector into new
research observations and immutable alerts. The UI does not join historical
records to the mutable current reference cache.

* Complete profiles: **7-day TTL**, no provider request or metadata write while fresh.
* Not found, partial profiles, provider failure or missing credentials: **24-hour retry**.
* Retry deadline is committed before HTTP; crashes/restarts do not trigger immediate retries.
* Refreshes never replace known fields with missing/UNKNOWN values. A partial refresh
  merges usable fields and retains older values for omitted fields. Source/retrieved_at
  describe the latest accepted profile, not per-field freshness.
* At most **40 sequential requests** and a **20-second soft scheduling budget** per
  universe resolution. An in-flight request can exceed that budget. Remaining due
  symbols are deferred to a later cycle and retain cache/fallback/UNKNOWN meanwhile.
* HTTP connect/read timeouts are **3/5 seconds**, with no retries or redirects.
  Read timeout is an inactivity timeout, not a strict total wall-clock deadline.
* The first timeout/HTTP/network/malformed failure stops further provider calls in
  that batch. Remaining processed due symbols receive the 24-hour retry deadline.
  Not-found and partial profiles do not stop other symbols.
* Cache read/write failures are logged generically and do not abort discovery.
  A failed initial cache write prevents that symbol's HTTP call. Successful data
  must persist before it is supplied downstream.

The existing scanner advisory lock serializes runtime refreshes; V1 does not add
a distributed metadata worker or independent concurrent refresh support. Healthy,
fast responses for 32 missing symbols normally mean 32 initial requests and zero
on subsequent cycles until expiry. No bulk endpoint or new SDK is used.

## Precedence and schema

Known persisted classification wins over `config/sectors.json`. The optional file
only seeds missing/unknown sectors during a due resolution; it is not an override.
Removing the file or supplying UNKNOWN cannot erase known classification. A later
successful provider response may replace fallback classification. A fallback-only
known sector is retained rather than automatically rewritten when the file changes.

Migration **0014** extends existing `symbol_metadata` with company_name, CIK, ISIN,
CUSIP, exchange, country, last_attempt_at, next_refresh_at, and last_status. Existing
symbol, sector, industry, metadata_source, retrieved_at and updated_at are reused.
On initial UNKNOWN/fallback rows retrieved_at retains the existing non-null schema's
creation-time convention; last_status/source distinguish these from provider success.
The migration also adds nullable industry to `active_universe_members` so display
classification is published atomically with the cycle. No competing cache exists.
All new columns are nullable; old alerts/observations are untouched. Migration must
precede running updated services; it has only been applied to isolated test databases.
Retain the schema on application rollback: downgrade discards the added reference
fields and is intended only for disposable migration tests, not existing data.

## History and public boundary

New alerts snapshot the sector known to that cycle using unchanged Alert Foundation
semantics. Completed-candle gating, durable transitions and immutability are unchanged.
Legacy UNKNOWN alerts remain UNKNOWN; later enrichment/reclassification never
backfills alerts or research. Industry is cached and shown live; adding industry
or reference revisions to historical research/alert snapshots is outside this V1.

Public universe DTOs add **industry only**. Existing sector displays receive enriched
labels. Company identifiers, provider/source, refresh timestamps, status and raw
payloads remain private. Errors never include exception text or authenticated URLs.
Raw FMP sector/industry strings are retained without taxonomy normalization.

Licensing, retention and public-display suitability remain unresolved; this local
implementation is not deployment approval. Classification accuracy, corporate
actions/ticker reuse, field-level provenance and historical effective dates are not
solved by storing identifiers. No automatic backfill is included.

## Future — not implemented

```text
cached sector metadata + Alpaca/IEX intraday data
                         ↓
                 Sector Activity — Today
```

No activity/strength metric, sector trading rule, Backtest or Discord feature is added.
