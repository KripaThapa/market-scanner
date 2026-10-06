"""Literal directional numeric watchlist instructions; no inferred trading rules."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re


@dataclass(frozen=True)
class LevelInstruction:
    direction: str
    price: Decimal


CONDITION = re.compile(
    r'\b(?P<direction>LONG|SHORT)\s*(?P<operator>above\b|over\b|below\b|under\b|[<>])'
    r'\s*\$?\s*(?P<price>\d+(?:\.\d+)?)(?![\w/-]|\.[\d.])', re.IGNORECASE)


def price_value(value):
    try:
        price = Decimal(str(value))
        if not price.is_finite() or price <= 0 or price >= Decimal('10000000000000000'):
            return None
        exact = price.quantize(Decimal('.00000001'))
        return exact if exact == price else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def parse_levels(note):
    """Only LONG above/over/> N and SHORT below/under/< N are actionable.

    No pivot, target, No Go, range, PMH/PDL, or indicator interpretation. The
    original note is never altered. Repeated literal conditions are deduplicated.
    """
    levels = []
    for match in CONDITION.finditer(note or ''):
        direction = match['direction'].upper()
        operator = match['operator'].lower()
        if (direction == 'LONG') != (operator in {'above', 'over', '>'}):
            continue
        # Explicit negation is context, not an instruction to monitor that price.
        prefix = (note or '')[max(0, match.start() - 30):match.start()]
        if re.search(r"\b(?:no|not|avoid|never|don't|do not)\s+(?:go\s+)?$", prefix, re.I):
            continue
        tail = (note or '')[match.end():]
        if re.match(r'\s*(?:[/–%\-]|to\b|percent\b|,\s*\d)', tail, re.I):
            continue
        price = price_value(match['price'])
        if price is not None:
            level = LevelInstruction(direction, price)
            if level not in levels:
                levels.append(level)
    return tuple(levels)


NO_GO = re.compile(r'\bno\s+go\s+(?:under|below)\s+\$?\s*(\d+(?:\.\d+)?)(?![\w/-]|\.[\d.])', re.I)


def parse_pivots(cell):
    """Strict numeric cell, optionally slash-separated; never extract numbers from prose."""
    if not re.fullmatch(r'\s*\$?\d+(?:\.\d+)?(?:\s*/\s*\$?\d+(?:\.\d+)?)*\s*', cell or ''):
        return ()
    values = [price_value(part.strip().lstrip('$')) for part in cell.split('/')]
    if any(value is None for value in values):
        return ()
    return tuple(dict.fromkeys(values))


def lookout_instructions(fields, fallback_note=None):
    """Only validated cells and literal directional/warning clauses create monitors."""
    result = []
    for semantic, key in (('SUPPORT', 'support_pivots'), ('RESISTANCE', 'resistance_pivots')):
        for value in fields.get(key, []) or []:
            price = price_value(value)
            if price is not None:
                result.append({'direction': 'LEVEL', 'semantic': semantic, 'trigger_level': str(price)})
    # Without reliable column geometry retain the existing literal-only parser.
    plan = fields.get('game_plan') if fields.get('columns_detected') else fallback_note
    if fields.get('game_plan_reliable') is False or fields.get('literal_reliable') is False:
        plan = None
    if plan:
        for level in parse_levels(plan):
            result.append({'direction': level.direction, 'semantic': level.direction,
                           'trigger_level': str(level.price)})
        for match in NO_GO.finditer(plan):
            tail = plan[match.end():]
            if re.match(r'\s*(?:[/–%\-]|to\b|percent\b|,\s*\d)', tail, re.I):
                continue
            price = price_value(match[1])
            if price is not None:
                result.append({'direction': 'LEVEL', 'semantic': 'NO_GO', 'trigger_level': str(price)})
    return list({(item['semantic'], item['trigger_level']): item for item in result}.values())
