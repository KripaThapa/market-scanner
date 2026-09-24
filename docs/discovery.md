# Discovery Engine V1

Discovery answers which symbols enter the active scanning universe. It does not add an entry rule or change Experimental Forming Setup V1.

The worker merges the current uploaded watchlist with Alpaca Screener Most Actives, Top Gainers, and Top Losers. Symbols are normalized and scanned once per cycle. Every source membership is retained internally, including overlaps. The Alpaca Screener response is distinct from the Alpaca/IEX candle feed; metrics are kept only when the provider supplies them. Automatic sources are refreshed independently only when discovery is enabled, the configured 08:00 inclusive–10:00 exclusive America/Chicago research window is open, and the date is an XNYS session. The worker uses Strategy Lab's shared XNYS calendar; weekends and exchange holidays skip automatic discovery. Defaults: `DISCOVERY_ENABLED=true`, `DISCOVERY_INTERVAL_SECONDS=300`, `DISCOVERY_TOP_N=10`. A failed source is logged and marked FAILED, and its same-day last-known membership remains; a successful empty response removes its membership. Outside the window, an existing active universe remains available for scanner processing without automatic screener refresh. On a non-session, a discovery-sourced active snapshot is not scanned; an uploaded manual watchlist may still use the existing scanner path, but automatic discovery is disabled.

`discovery_memberships` holds current same-day membership and first/last seen timestamps. `discovery_events` preserves appearances, changes, and departures. `discovery_source_status` distinguishes OK, EMPTY, and FAILED. `research_observation_sources` records every source attached to each observation. These tables are internal research data. Public DTOs contain no source type or upload/image identity.

Sector metadata comes from optional read-only `config/sectors.json` symbol mapping. Alpaca's asset object does not supply sector/industry here. Unmapped symbols are `UNKNOWN` and still scanned. `symbol_metadata` caches sector and source; changes are updated when the configured mapping changes. `sector_snapshots` stores objective universe, context, and forming counts. No sector-strength score, ranking, or confirmation rule exists.

Candle timestamps denote the start of a candle. For an evaluation time T, a 3m candle is COMPLETED when T is at or after start + 3 minutes, and PARTIAL before then; 10m follows the same rule with 10 minutes. Conversion is timezone-aware through America/New_York and UTC. The current detector can evaluate a partial 3m candle; such decisions remain eligible under existing behavior and are tagged PARTIAL. Old observations may have unknown/null metadata; history is not invented.

The normal Discovery page is a source-agnostic universe page. It shows symbol, sector, price, context, setup, candle state, and update time, with sector filtering and symbol navigation. Source filtering belongs only in future authenticated research tooling. There is no Finviz integration or website scraping. Future objective screens can be added through the provider-neutral discovery result model.

The private Strategy Lab **Daily Watchlist** workflow stages screenshot extraction for owner review, then activates the validated upload through the existing watchlist snapshot pointer. The upload is retained as a dated record. On the next normal scanner cycle, DiscoveryService unions its `UPLOADED_WATCHLIST` membership with Alpaca source memberships, deduplicates by symbol, and the existing scanner processes each union member once. No frontend scan is started. Upload and provenance endpoints remain on the private internal API; the public API does not expose them.

Alert Foundation V1 sector investigation: `config/sectors.json` is not shipped
in this checkout. The pinned Alpaca SDK's Asset, ActiveStock and Mover models
supply no sector/industry fields, and the current adapters do not enrich them.
Sector enrichment is therefore DEFERRED; a licensed/trusted classification
source with symbol coverage, retrieval dates and update policy is needed.
No classification is inferred from prices, names or discovery sources. The
Dashboard's **Known sectors** excludes UNKNOWN/Unclassified, and separately
counts stocks missing sector data. Existing configured mappings still work.
