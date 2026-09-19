"""Alpaca Screener adapter; its results are separate from IEX candle provenance."""

from .domain import DiscoveryItem, SourceType, normalize_symbol


class AlpacaDiscoveryProvider:
    name = 'Alpaca Screener'

    def __init__(self, api_key, secret_key, *, client=None, top=10):
        if client is None:
            from alpaca.data.historical.screener import ScreenerClient
            client = ScreenerClient(api_key, secret_key)
        self.client = client
        self.top = top
        self._movers = None

    def fetch(self, source_type, at):
        from alpaca.data.requests import MarketMoversRequest, MostActivesRequest
        from alpaca.data.enums import MarketType
        if source_type == SourceType.MOST_ACTIVE:
            response = self.client.get_most_actives(MostActivesRequest(top=self.top))
            rows = response.most_actives
            metric_names = ('volume', 'trade_count')
        elif source_type in (SourceType.TOP_GAINER, SourceType.TOP_LOSER):
            if self._movers is None:
                self._movers = self.client.get_market_movers(
                    MarketMoversRequest(top=self.top, market_type=MarketType.STOCKS))
            rows = self._movers.gainers if source_type == SourceType.TOP_GAINER else self._movers.losers
            metric_names = ('percent_change', 'change', 'price')
        else:
            raise ValueError('Unsupported automatic discovery source')
        output = []
        for rank, row in enumerate(rows, 1):
            symbol = normalize_symbol(row.symbol)
            if symbol:
                output.append(DiscoveryItem(symbol, source_type, self.name, at, rank,
                    {key: getattr(row, key) for key in metric_names
                     if getattr(row, key, None) is not None}))
        return output
