"""Persistent data, not additional strategy rules. Schema changes require Alembic."""

from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WatchlistUpload(Base):
    __tablename__ = 'watchlist_uploads'
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(20))
    original_filename: Mapped[str | None] = mapped_column(String(180))
    stored_filename: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0)
    processing_status: Mapped[str] = mapped_column(String(30))
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    validated_count: Mapped[int] = mapped_column(Integer, default=0)
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class WatchlistSymbol(Base):
    __tablename__ = 'watchlist_symbols'
    __table_args__ = (UniqueConstraint('watchlist_upload_id', 'symbol', name='uq_watchlist_symbol'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_upload_id: Mapped[int] = mapped_column(ForeignKey('watchlist_uploads.id'), index=True)
    symbol: Mapped[str] = mapped_column(Text)
    validation_status: Mapped[str] = mapped_column(String(20))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScanResultModel(Base):
    __tablename__ = 'scan_results'
    __table_args__ = (UniqueConstraint('snapshot_id', 'symbol', name='uq_scan_symbol'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey('watchlist_uploads.id'), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[float | None] = mapped_column(Float)
    context_10m: Mapped[str] = mapped_column(String(20))
    context_3m: Mapped[str] = mapped_column(String(20))
    vwap_position: Mapped[str | None] = mapped_column(String(10))
    vwap: Mapped[float | None] = mapped_column(Float)
    ema_5: Mapped[float | None] = mapped_column(Float)
    ema_12: Mapped[float | None] = mapped_column(Float)
    ema_34: Mapped[float | None] = mapped_column(Float)
    ema_50: Mapped[float | None] = mapped_column(Float)
    analysis_3m: Mapped[dict | None] = mapped_column(JSON)
    candles_10m: Mapped[list | None] = mapped_column(JSON)
    candles_3m: Mapped[list | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class FormingSetup(Base):
    __tablename__ = 'forming_setups'
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey('watchlist_uploads.id'), index=True)
    symbol: Mapped[str] = mapped_column(String(20))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_candle_at: Mapped[str | None] = mapped_column(String(40))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context_10m: Mapped[str | None] = mapped_column(String(20))
    setup_state: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    distance_status: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    price: Mapped[float | None] = mapped_column(Float)
    ema_5: Mapped[float | None] = mapped_column(Float)
    ema_12: Mapped[float | None] = mapped_column(Float)
    ema_34: Mapped[float | None] = mapped_column(Float)
    ema_50: Mapped[float | None] = mapped_column(Float)
    vwap_position: Mapped[str | None] = mapped_column(String(10))


class Alert(Base):
    __tablename__ = 'alerts'
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20))
    alert_type: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    destination: Mapped[str | None] = mapped_column(Text)
    delivery_status: Mapped[str | None] = mapped_column(Text)


class SectorMetric(Base):
    __tablename__ = 'sector_metrics'
    __table_args__ = (UniqueConstraint('snapshot_id', 'sector', name='uq_snapshot_sector'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey('watchlist_uploads.id'), index=True)
    sector: Mapped[str] = mapped_column(Text)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    symbols: Mapped[list] = mapped_column(JSON)
    symbol_count: Mapped[int] = mapped_column(Integer)
    bullish_count: Mapped[int] = mapped_column(Integer)
    bearish_count: Mapped[int] = mapped_column(Integer)
    volatility_metric: Mapped[float | None] = mapped_column(Float)
    relative_strength_metric: Mapped[float | None] = mapped_column(Float)


class AppState(Base):
    __tablename__ = 'app_state'
    id: Mapped[int] = mapped_column(primary_key=True)
    active_watchlist_id: Mapped[int | None] = mapped_column(ForeignKey('watchlist_uploads.id'))
    current_snapshot: Mapped[int | None] = mapped_column(ForeignKey('watchlist_uploads.id'))
    status: Mapped[str] = mapped_column(String(30), default='idle')
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_updated: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    scanner_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scan_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)


class StrategyVersion(Base):
    __tablename__ = 'strategy_versions'
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    config_snapshot: Mapped[dict] = mapped_column(JSON)
    rules_snapshot: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResearchCandle(Base):
    __tablename__ = 'research_candles'
    __table_args__ = (UniqueConstraint('symbol', 'timeframe', 'candle_at', 'provider',
                                       'feed', 'content_hash', name='uq_research_candle_revision'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(3))
    source_timeframe: Mapped[str] = mapped_column(String(3))
    candle_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    feed: Mapped[str] = mapped_column(String(40))
    session_policy: Mapped[str] = mapped_column(String(80))
    source_timezone: Mapped[str] = mapped_column(String(60))
    content_hash: Mapped[str] = mapped_column(String(64))
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)
    ema_5: Mapped[float | None] = mapped_column(Float)
    ema_12: Mapped[float | None] = mapped_column(Float)
    ema_34: Mapped[float | None] = mapped_column(Float)
    ema_50: Mapped[float | None] = mapped_column(Float)
    vwap: Mapped[float | None] = mapped_column(Float)


class ResearchObservation(Base):
    __tablename__ = 'research_observations'
    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(220), unique=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey('watchlist_uploads.id'), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trading_date: Mapped[str] = mapped_column(String(10), index=True)
    strategy_version: Mapped[str] = mapped_column(ForeignKey('strategy_versions.id'), index=True)
    watchlist_source: Mapped[str] = mapped_column(String(20))
    watchlist_filename: Mapped[str | None] = mapped_column(String(180))
    sector: Mapped[str | None] = mapped_column(String(100), index=True)
    price: Mapped[float | None] = mapped_column(Float)
    context_10m: Mapped[str] = mapped_column(String(20))
    context_3m: Mapped[str] = mapped_column(String(20))
    setup_state: Mapped[str] = mapped_column(String(30), index=True)
    detector_reason: Mapped[str | None] = mapped_column(Text)
    three_min_candle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ten_min_candle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ema_5_3m: Mapped[float | None] = mapped_column(Float)
    ema_12_3m: Mapped[float | None] = mapped_column(Float)
    ema_34_3m: Mapped[float | None] = mapped_column(Float)
    ema_50_3m: Mapped[float | None] = mapped_column(Float)
    ema_5_10m: Mapped[float | None] = mapped_column(Float)
    ema_12_10m: Mapped[float | None] = mapped_column(Float)
    ema_34_10m: Mapped[float | None] = mapped_column(Float)
    ema_50_10m: Mapped[float | None] = mapped_column(Float)
    vwap_3m: Mapped[float | None] = mapped_column(Float)
    vwap_10m: Mapped[float | None] = mapped_column(Float)
    vwap_position_3m: Mapped[str | None] = mapped_column(String(10))
    vwap_position_10m: Mapped[str | None] = mapped_column(String(10))
    volume_3m: Mapped[float | None] = mapped_column(Float)
    volume_10m: Mapped[float | None] = mapped_column(Float)
    inside_research_window: Mapped[bool] = mapped_column(Boolean)
    provider: Mapped[str] = mapped_column(String(40))
    feed: Mapped[str] = mapped_column(String(40))
    source_timeframe: Mapped[str] = mapped_column(String(3))
    session_policy: Mapped[str] = mapped_column(String(80))
    market_timezone: Mapped[str] = mapped_column(String(60))
    research_timezone: Mapped[str] = mapped_column(String(60))
    data_status: Mapped[str] = mapped_column(String(30))
    discovery_sources: Mapped[list | None] = mapped_column(JSON)
    candle_state: Mapped[str | None] = mapped_column(String(12), index=True)
    decision_eligible: Mapped[bool | None] = mapped_column(Boolean, index=True)
    sector_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey('sector_snapshots.id', name='fk_observation_sector_snapshot'))


class DiscoveryMembership(Base):
    __tablename__ = 'discovery_memberships'
    __table_args__ = (UniqueConstraint('trading_date', 'symbol', 'source_type',
                                       name='uq_discovery_membership'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    trading_date: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    source_type: Mapped[str] = mapped_column(String(30), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean)
    rank: Mapped[int | None] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON)


class ResearchObservationSource(Base):
    __tablename__ = 'research_observation_sources'
    __table_args__ = (UniqueConstraint('observation_id', 'source_type',
                                       name='uq_observation_source'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey('research_observations.id'), index=True)
    source_type: Mapped[str] = mapped_column(String(30), index=True)


class DiscoveryEvent(Base):
    __tablename__ = 'discovery_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    trading_date: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    source_type: Mapped[str] = mapped_column(String(30), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    active: Mapped[bool] = mapped_column(Boolean)
    rank: Mapped[int | None] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSON)


class DiscoverySourceStatus(Base):
    __tablename__ = 'discovery_source_status'
    source_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    provider: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(200))


class SymbolMetadata(Base):
    __tablename__ = 'symbol_metadata'
    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    sector: Mapped[str] = mapped_column(String(100), index=True)
    industry: Mapped[str | None] = mapped_column(String(120))
    metadata_source: Mapped[str] = mapped_column(String(80))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ActiveUniverseMember(Base):
    __tablename__ = 'active_universe_members'
    __table_args__ = (UniqueConstraint('snapshot_id', 'symbol', name='uq_universe_symbol'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey('watchlist_uploads.id'), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    sources: Mapped[list] = mapped_column(JSON)
    source_metrics: Mapped[dict] = mapped_column(JSON)
    sector: Mapped[str] = mapped_column(String(100))
    candle_state: Mapped[str | None] = mapped_column(String(12))
    decision_eligible: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SectorSnapshot(Base):
    __tablename__ = 'sector_snapshots'
    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey('watchlist_uploads.id'), index=True)
    sector: Mapped[str] = mapped_column(String(100), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    trading_date: Mapped[str] = mapped_column(String(10), index=True)
    symbols: Mapped[list] = mapped_column(JSON)
    symbol_count: Mapped[int] = mapped_column(Integer)
    bullish_count: Mapped[int] = mapped_column(Integer)
    bearish_count: Mapped[int] = mapped_column(Integer)
    mixed_count: Mapped[int] = mapped_column(Integer)
    forming_long_count: Mapped[int] = mapped_column(Integer)
    forming_short_count: Mapped[int] = mapped_column(Integer)


class ResearchOutcome(Base):
    __tablename__ = 'research_outcomes'
    id: Mapped[int] = mapped_column(primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey('research_observations.id'), unique=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_future_candles: Mapped[int] = mapped_column(Integer)
    future_3_candle_return: Mapped[float | None] = mapped_column(Float)
    future_5_candle_return: Mapped[float | None] = mapped_column(Float)
    future_10_candle_return: Mapped[float | None] = mapped_column(Float)
    maximum_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    maximum_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    time_to_mfe_minutes: Mapped[float | None] = mapped_column(Float)
    time_to_mae_minutes: Mapped[float | None] = mapped_column(Float)


class RuleProposal(Base):
    __tablename__ = 'rule_proposals'
    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_version: Mapped[str] = mapped_column(ForeignKey('strategy_versions.id'))
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default='PROPOSED')
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    timeframe: Mapped[str] = mapped_column(String(10))
    condition: Mapped[str] = mapped_column(Text)
    threshold_config: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StrategyReplaySession(Base):
    __tablename__ = 'strategy_replay_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    instrument: Mapped[str] = mapped_column(String(40), index=True)
    asset_type: Mapped[str] = mapped_column(String(12), index=True)
    market_date: Mapped[str] = mapped_column(String(10), index=True)
    timezone: Mapped[str] = mapped_column(String(60))
    visible_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    visible_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_replay_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    strategy_version: Mapped[str | None] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(40))
    feed: Mapped[str] = mapped_column(String(40))
    session_configuration: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    blind_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    outcome_revealed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StrategyReplayCandle(Base):
    __tablename__ = 'strategy_replay_candles'
    __table_args__ = (UniqueConstraint('replay_id', 'candle_at', name='uq_replay_source_candle'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    replay_id: Mapped[int] = mapped_column(ForeignKey('strategy_replay_sessions.id'), index=True)
    candle_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    trade_count: Mapped[float | None] = mapped_column(Float)


class StrategyReplayObservation(Base):
    __tablename__ = 'strategy_replay_observations'
    id: Mapped[int] = mapped_column(primary_key=True)
    replay_id: Mapped[int] = mapped_column(ForeignKey('strategy_replay_sessions.id'), index=True)
    instrument: Mapped[str] = mapped_column(String(40), index=True)
    market_date: Mapped[str] = mapped_column(String(10), index=True)
    replay_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    decision: Mapped[str] = mapped_column(String(30))
    free_text_reason: Mapped[str] = mapped_column(Text)
    strategy_version: Mapped[str | None] = mapped_column(String(80))
    observed_price: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BaselineRun(Base):
    __tablename__ = 'baseline_runs'
    __table_args__ = (UniqueConstraint('start_date', 'end_date', 'strategy_version',
                                       'run_type', 'universe_key',
                                       name='uq_baseline_run_experiment'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    start_date: Mapped[str] = mapped_column(String(10), index=True)
    end_date: Mapped[str] = mapped_column(String(10), index=True)
    strategy_version: Mapped[str] = mapped_column(String(80), index=True)
    run_type: Mapped[str] = mapped_column(String(40), default='LIVE_RECORDED_UNIVERSE', index=True)
    universe_key: Mapped[str] = mapped_column(String(64), default='LIVE')
    universe_symbols: Mapped[list] = mapped_column(JSON, default=list)
    research_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), index=True)
    trading_days_total: Mapped[int] = mapped_column(Integer)
    trading_days_completed: Mapped[int] = mapped_column(Integer, default=0)
    symbol_failures: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BaselineDay(Base):
    __tablename__ = 'baseline_days'
    __table_args__ = (UniqueConstraint('run_id', 'market_date', name='uq_baseline_run_day'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('baseline_runs.id'), index=True)
    market_date: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    symbols_total: Mapped[int] = mapped_column(Integer, default=0)
    symbols_completed: Mapped[int] = mapped_column(Integer, default=0)
    symbols_failed: Mapped[int] = mapped_column(Integer, default=0)
    coverage_limitation: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BaselineSymbolDay(Base):
    __tablename__ = 'baseline_symbol_days'
    __table_args__ = (UniqueConstraint('baseline_run_id', 'market_date', 'symbol',
                                       'strategy_version',
                                       name='uq_baseline_run_symbol_day_version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    baseline_run_id: Mapped[int | None] = mapped_column(ForeignKey('baseline_runs.id'), index=True)
    market_date: Mapped[str] = mapped_column(String(10), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    strategy_version: Mapped[str] = mapped_column(String(80), index=True)
    replay_id: Mapped[int | None] = mapped_column(ForeignKey('strategy_replay_sessions.id'))
    status: Mapped[str] = mapped_column(String(20), index=True)
    sector: Mapped[str | None] = mapped_column(String(100))
    provenance: Mapped[list] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BaselineEvaluation(Base):
    __tablename__ = 'baseline_evaluations'
    __table_args__ = (UniqueConstraint('symbol_day_id', 'evaluated_at',
                                       name='uq_baseline_symbol_evaluation'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_day_id: Mapped[int] = mapped_column(ForeignKey('baseline_symbol_days.id'), index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    context_10m: Mapped[str] = mapped_column(String(20))
    state_3m: Mapped[str] = mapped_column(String(30), index=True)
    price: Mapped[float | None] = mapped_column(Float)
    ema_5: Mapped[float | None] = mapped_column(Float)
    ema_12: Mapped[float | None] = mapped_column(Float)
    ema_34: Mapped[float | None] = mapped_column(Float)
    ema_50: Mapped[float | None] = mapped_column(Float)
    vwap: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(40))
    feed: Mapped[str] = mapped_column(String(40))
    candle_state: Mapped[str] = mapped_column(String(12))
    decision_eligible: Mapped[bool] = mapped_column(Boolean)


class BaselineEpisode(Base):
    __tablename__ = 'baseline_episodes'
    __table_args__ = (UniqueConstraint('symbol_day_id', 'setup_state', 'first_forming_at',
                                       name='uq_baseline_episode_anchor'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_day_id: Mapped[int] = mapped_column(ForeignKey('baseline_symbol_days.id'), index=True)
    setup_state: Mapped[str] = mapped_column(String(30), index=True)
    first_forming_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observation_price: Mapped[float | None] = mapped_column(Float)
    context_10m: Mapped[str] = mapped_column(String(20))
    available_future_bars: Mapped[int] = mapped_column(Integer, default=0)
    return_after_3_bars: Mapped[float | None] = mapped_column(Float)
    return_after_5_bars: Mapped[float | None] = mapped_column(Float)
    return_after_10_bars: Mapped[float | None] = mapped_column(Float)
    maximum_favorable_excursion: Mapped[float | None] = mapped_column(Float)
    maximum_adverse_excursion: Mapped[float | None] = mapped_column(Float)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
