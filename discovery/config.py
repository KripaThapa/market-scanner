"""Discovery refresh configuration."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DiscoverySettings:
    enabled: bool = False
    interval_seconds: int = 300
    top: int = 10


def load_settings():
    enabled = os.getenv('AUTO_DISCOVERY_ENABLED', 'false').strip().lower()
    if enabled not in ('true', 'false'):
        raise ValueError('AUTO_DISCOVERY_ENABLED must be true or false')
    interval = int(os.getenv('DISCOVERY_INTERVAL_SECONDS', '300'))
    top = int(os.getenv('DISCOVERY_TOP_N', '10'))
    if interval < 30 or not 1 <= top <= 100:
        raise ValueError('Discovery interval must be at least 30 seconds and top N in 1..100')
    return DiscoverySettings(enabled == 'true', interval, top)
