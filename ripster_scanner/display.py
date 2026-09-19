"""Console presentation of the current context summaries."""


def trend_icon(trend: str) -> str:

    if trend == "BULLISH":
        return "🟢"

    if trend == "BEARISH":
        return "🔴"

    return "🟡"


def print_analysis(
    symbol: str,
    analysis_10m: dict,
    analysis_3m: dict
):

    print()
    print("=" * 50)
    print(f"        RIPSTER SCANNER — {symbol}")
    print("=" * 50)

    print("\n10 MINUTE CONTEXT")
    print("-" * 50)

    print(
        f"Trend:       "
        f"{trend_icon(analysis_10m['trend'])} "
        f"{analysis_10m['trend']}"
    )

    print(
        f"5/12 Cloud:  "
        f"{analysis_10m['fast_cloud']}"
    )

    print(
        f"34/50 Cloud: "
        f"{analysis_10m['slow_cloud']}"
    )

    print(
        f"VWAP:        "
        f"{analysis_10m['vwap_position']}"
    )

    print(
        f"Price:       "
        f"${analysis_10m['close']:.2f}"
    )

    print(
        f"VWAP Price:  "
        f"${analysis_10m['vwap']:.2f}"
    )

    print("\n3 MINUTE ENTRY CONTEXT")
    print("-" * 50)

    print(
        f"Trend:       "
        f"{trend_icon(analysis_3m['trend'])} "
        f"{analysis_3m['trend']}"
    )

    print(
        f"5/12 Cloud:  "
        f"{analysis_3m['fast_cloud']}"
    )

    print(
        f"34/50 Cloud: "
        f"{analysis_3m['slow_cloud']}"
    )

    print(
        f"VWAP:        "
        f"{analysis_3m['vwap_position']}"
    )

    print()
    print("=" * 50)


def print_watchlist_summary(results):
    """Print 10-minute VWAP position and group by 10-minute context only."""
    print("\nRIPSTER WATCHLIST SCAN\n")
    width = max(8, max((len(result.symbol) for result in results), default=0) + 2)
    print(f"{'SYMBOL':<{width}} {'10M':<10} {'3M':<10} VWAP")
    for result in results:
        if result.has_data:
            print(f"{result.symbol:<{width}} {result.analysis_10m['trend']:<10} "
                  f"{result.analysis_3m['trend']:<10} {result.analysis_10m['vwap_position']}")
        else:
            print(f"{result.symbol:<{width}} {'NO DATA':<10} {'NO DATA':<10} —")

    for title, trend in [("Potential Long Context", "BULLISH"),
                         ("Potential Short Context", "BEARISH"),
                         ("Mixed / Ignore", "MIXED")]:
        print(f"\n{title}:")
        symbols = [result.symbol for result in results
                   if result.has_data and result.analysis_10m['trend'] == trend]
        for symbol in symbols:
            print(f"* {symbol}")
        if not symbols:
            print("* None")


def print_watchlist_import(imported):
    """Show accepted symbols and every filtered token with its rejection reason."""
    print("\nRIPSTER WATCHLIST IMPORT")
    print("\nExtracted candidates:")
    for candidate in imported.candidates:
        print(candidate)
    if not imported.candidates:
        print("(none)")
    print("\nValidated:")
    for symbol in imported.validated:
        print(symbol)
    if not imported.validated:
        print("(none)")
    print("\nRejected / uncertain:")
    for rejection in imported.rejected:
        print(f"{rejection.candidate}: {rejection.reason}")
    if not imported.rejected:
        print("(none)")
    print(f"\n{len(imported.validated)} valid symbols loaded.")
