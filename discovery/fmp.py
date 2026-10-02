"""FMP reference profiles only. No prices or SDK objects leave this adapter."""

import requests

from .metadata_provider import CompanyMetadata, MetadataResult, usable


class FMPMetadataProvider:
    name = 'FMP'
    endpoint = 'https://financialmodelingprep.com/stable/profile'

    def __init__(self, api_key, *, client=None):
        self._api_key = api_key
        self._client = client or requests

    def fetch(self, symbol):
        if not self._api_key:
            return MetadataResult('UNAVAILABLE')
        try:
            with self._client.get(self.endpoint,
                    params={'symbol': symbol, 'apikey': self._api_key},
                    timeout=(3, 5), allow_redirects=False) as response:
                if response.status_code != 200:
                    return MetadataResult('HTTP_ERROR')
                payload = response.json()
        except requests.Timeout:
            return MetadataResult('TIMEOUT')
        except requests.RequestException:
            return MetadataResult('UNAVAILABLE')
        except ValueError:
            return MetadataResult('MALFORMED')
        if payload == []:
            return MetadataResult('NOT_FOUND')
        if (not isinstance(payload, list) or len(payload) != 1
                or not isinstance(payload[0], dict) or payload[0].get('symbol') != symbol):
            return MetadataResult('MALFORMED')
        row = payload[0]

        def field(name, limit):
            value = usable(row.get(name), limit)
            return None if value and self._api_key in value else value

        metadata = CompanyMetadata(symbol=symbol,
            company_name=field('companyName', 240), sector=field('sector', 100),
            industry=field('industry', 120), cik=field('cik', 20),
            isin=field('isin', 20), cusip=field('cusip', 20),
            exchange=field('exchange', 80), country=field('country', 80))
        status = 'OK' if metadata.company_name and metadata.sector and metadata.industry else 'PARTIAL'
        return MetadataResult(status, metadata)
