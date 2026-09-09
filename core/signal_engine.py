"""Pure H1 signal-family rules, separated from indicator calculation and I/O."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalFeatures:
    market_regime: str
    close: float
    ema20: float
    ema50: float
    return20_pct: float
    volume_ratio: float
    rsi: float
    bullish_body: bool
    close_location: float
    body_fraction: float
    upper_wick_fraction: float
    lower_wick_fraction: float


def is_selling_climax_reversal(
    f: SignalFeatures,
    *,
    max_return20: float,
    max_rsi: float,
    min_volume_ratio: float,
) -> bool:
    return (
        f.return20_pct <= max_return20
        and f.rsi <= max_rsi
        and f.volume_ratio >= min_volume_ratio
        and f.bullish_body
        and f.close_location >= 0.60
        and f.lower_wick_fraction >= 0.20
    )
