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
