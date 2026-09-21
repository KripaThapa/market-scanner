"""Read-only Strategy Lab view of active scanner rules and proposed research."""

ACTIVE_RULE_CONTEXT = {
    'Fast EMA direction': {
        'affects': 'BOTH',
        'why_can_fail': (
            'LONG context needs EMA 5 above EMA 12; SHORT context needs EMA 5 below EMA 12. '
            'Equality satisfies neither direction.'),
    },
    'Slow EMA direction': {
        'affects': 'BOTH',
        'why_can_fail': (
            'LONG context needs EMA 34 above EMA 50; SHORT context needs EMA 34 below EMA 50. '
            'Equality satisfies neither direction.'),
    },
    'Price versus clouds and VWAP': {
        'affects': 'BOTH',
        'why_can_fail': (
            'LONG context needs the close strictly above VWAP and all four EMAs; '
            'SHORT context needs it strictly below all five values.'),
    },
    'Directional context': {
        'affects': 'BOTH',
        'why_can_fail': (
            'The 3m setup returns NONE unless 10m context is BULLISH for LONG '
            'or BEARISH for SHORT.'),
    },
    'Prior move lookback': {
        'affects': 'BOTH',
        'why_can_fail': (
            'The detector needs the configured number of preceding 3m bars plus the latest bar, '
            'with finite price and EMA inputs.'),
    },
    'Minimum retrace': {
        'affects': 'BOTH',
        'why_can_fail': (
            'The pullback/bounce from the preceding high/low is insufficient when its retrace '
            'is below the configured minimum.'),
    },
    'Fast cloud proximity': {
        'affects': 'BOTH',
        'why_can_fail': (
            'The latest close is too far from the 3m EMA 5/12 cloud; distance is zero inside '
            'the cloud and otherwise measured to its nearest edge.'),
    },
    'Slow cloud structure': {
        'affects': 'BOTH',
        'why_can_fail': (
            'LONG needs EMA 34 above EMA 50 and price no farther below the cloud than its '
            'tolerance; SHORT uses the reversed order and upper-edge tolerance.'),
    },
}


PROPOSED_RULES = [
    {
        'name': 'VIX Regime',
        'timeframe': 'Market context',
        'hypothesis': 'VIX > 17 may change how we treat long setups / may require waiting.',
        'machine_definition': 'TBD',
    },
    {
        'name': 'MTF Daily 20/21 Cloud',
        'timeframe': 'Daily',
        'hypothesis': 'Research the EMA 20/21 cloud as multi-timeframe context or magnet behavior.',
        'parameters': {'emas': [20, 21], 'source': 'hl2'},
    },
    {
        'name': 'MTF Daily 50/55 Cloud',
        'timeframe': 'Daily',
        'hypothesis': 'Research the EMA 50/55 cloud as multi-timeframe context or magnet behavior.',
        'parameters': {'emas': [50, 55], 'source': 'hl2'},
    },
    {
        'name': 'EMA 5/12 Curl',
        'timeframe': 'TBD',
        'hypothesis': 'Research a machine-defined EMA 5/12 curl concept.',
        'machine_definition': 'TBD',
    },
    {
        'name': 'EMA 34/50 Curl',
        'timeframe': 'TBD',
        'hypothesis': 'Research a machine-defined EMA 34/50 curl concept.',
        'machine_definition': 'TBD',
    },
    {
        'name': 'First Pullback',
        'timeframe': 'TBD',
        'hypothesis': 'Research a first-pullback concept.',
        'machine_definition': 'TBD',
    },
    {
        'name': 'Watchlist Levels',
        'timeframe': 'TBD',
        'hypothesis': 'Research uploaded watchlist levels as contextual information.',
        'machine_definition': 'TBD',
        'limitation': 'Uploaded watchlist notes and levels are not currently used by FORMING.',
    },
]


def strategy_lab_rules_catalog(strategy_catalog):
    """Build the private display catalog from scanner definitions and fixed hypotheses."""
    active_rules = []
    for definition in strategy_catalog['rules']:
        context = ACTIVE_RULE_CONTEXT.get(definition['name'])
        if context is None:
            continue
        value = definition['value']
        parameter = None
        if definition['name'] == 'Prior move lookback':
            parameter = f'{value} preceding 3m bars'
        elif value is not None:
            parameter = f'{value * 100:.3g}%'
        active_rules.append({
            'name': definition['name'],
            'timeframe': ('10m + 3m' if definition['name'] == 'Directional context'
                          else definition['timeframe']),
            'status': 'ACTIVE',
            'implementation_stage': definition['status'],
            'check': definition['condition'],
            'affects': context['affects'],
            'why_can_fail': context['why_can_fail'],
            'configured_parameter': parameter,
        })

    proposed = [{**rule, 'status': 'PROPOSED', 'filtering': 'OFF'}
                for rule in PROPOSED_RULES]
    proposed.extend({
        'name': rule['name'],
        'timeframe': rule['timeframe'],
        'hypothesis': rule['description'],
        'machine_definition': rule['condition'] or 'TBD',
        'status': 'PROPOSED',
        'filtering': 'OFF',
    } for rule in strategy_catalog['proposals'] if rule.get('status') == 'PROPOSED')

    return {
        'strategy': strategy_catalog['strategy_version'],
        'strategy_name': strategy_catalog['strategy_name'],
        'strategy_maturity': 'EXPERIMENTAL',
        'active_rules': active_rules,
        'proposed_rules': proposed,
        'lifecycle_definitions': {
            'ACTIVE': 'Currently participates in FORMING_LONG / FORMING_SHORT decisions.',
            'EXPERIMENTAL': (
                'Machine-defined and being evaluated; this label alone does not mean a rule '
                'filters production decisions.'),
            'PROPOSED': 'Research hypothesis only; it does not affect scanner decisions.',
        },
    }
