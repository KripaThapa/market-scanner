"""Versioned, read-only description of the rules actually executed by the scanner."""

from dataclasses import asdict
import hashlib
import json

from .config import FormingThresholds

STRATEGY_VERSION = 'experimental-forming-v1'
STRATEGY_NAME = 'Experimental Forming Setup V1'


def strategy_version_id(thresholds: FormingThresholds) -> str:
    """Config changes get a distinct immutable version association."""
    encoded = json.dumps(asdict(thresholds), sort_keys=True, separators=(',', ':')).encode()
    return f'{STRATEGY_VERSION}/{hashlib.sha256(encoded).hexdigest()[:12]}'


def rule_definitions(thresholds: FormingThresholds):
    """Keep display values sourced from the scanner configuration."""
    rules = []
    def add(group, name, condition, rationale, status, value=None, enabled=True):
        rules.append({'group': group, 'name': name,
                      'timeframe': '10m' if group == '10-minute Context' else
                                   '3m' if group == '3-minute Forming Setup' else None,
                      'condition': condition,
                      'description': condition, 'rationale': rationale,
                      'status': status, 'value': value, 'enabled': enabled,
                      'rule_version': 1, 'strategy_version': strategy_version_id(thresholds)})
    add('10-minute Context', 'Fast EMA direction', 'BULLISH: EMA 5 > EMA 12; BEARISH: EMA 5 < EMA 12.',
        'Checks the direction of the fast EMA cloud.', 'IMPLEMENTED')
    add('10-minute Context', 'Slow EMA direction', 'BULLISH: EMA 34 > EMA 50; BEARISH: EMA 34 < EMA 50.',
        'Checks the direction of the larger EMA cloud.', 'IMPLEMENTED')
    add('10-minute Context', 'Price versus clouds and VWAP',
        'BULLISH: close above VWAP and all four EMAs; BEARISH: close below VWAP and all four EMAs.',
        'Requires price position to agree with both EMA clouds and session VWAP.', 'IMPLEMENTED')
    add('3-minute Forming Setup', 'Directional context',
        'FORMING_LONG requires 10m BULLISH; FORMING_SHORT requires 10m BEARISH.',
        'Keeps 10m direction separate from 3m setup development.', 'EXPERIMENTAL')
    add('3-minute Forming Setup', 'Prior move lookback',
        'Use preceding 3m bars, excluding the latest bar, for prior high or low.',
        'Defines the comparison window for pullback or bounce.', 'EXPERIMENTAL',
        thresholds.lookback_bars)
    add('3-minute Forming Setup', 'Minimum retrace',
        'LONG: (prior maximum high - latest close) / prior maximum high >= threshold; '
        'SHORT: (latest close - prior minimum low) / prior minimum low >= threshold.',
        'Requires a measurable move back from the recent extreme.', 'EXPERIMENTAL',
        thresholds.min_retrace_pct)
    add('3-minute Forming Setup', 'Fast cloud proximity',
        'Gap from latest close to nearest EMA 5/12 cloud edge, divided by close, <= threshold; zero inside cloud.',
        'Finds a pullback near the fast EMA cloud.', 'EXPERIMENTAL',
        thresholds.cloud_proximity_pct)
    add('3-minute Forming Setup', 'Slow cloud structure',
        'LONG: EMA 34 > EMA 50 and close >= min(EMA 34, EMA 50) × (1 - tolerance); '
        'SHORT: EMA 34 < EMA 50 and close <= max(EMA 34, EMA 50) × (1 + tolerance).',
        'Rejects pullbacks that lose the larger 3m EMA structure beyond tolerance.',
        'EXPERIMENTAL', thresholds.slow_cloud_tolerance_pct)
    add('Future', 'Entry trigger and grading', 'No entry trigger or A+/A/A- grading is defined.',
        'Reserved for separately specified and versioned work.', 'TBD', enabled=False)
    return rules
