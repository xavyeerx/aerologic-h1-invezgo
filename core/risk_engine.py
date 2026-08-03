"""Deterministic risk feasibility and position sizing for long candidates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import floor


@dataclass(frozen=True)
class RiskPolicy:
    risk_fraction: float = 0.0025
    max_total_open_risk_fraction: float = 0.02
    max_daily_new_risk_fraction: float = 0.01
    max_position_fraction: float = 0.20
    min_stop_pct: float = 1.0
    max_stop_pct: float = 5.0
    atr_stop_multiplier: float = 2.0
    lot_size: int = 100

    def __post_init__(self):
        fractions = (
            self.risk_fraction, self.max_total_open_risk_fraction,
            self.max_daily_new_risk_fraction, self.max_position_fraction,
        )
        if any(value <= 0 for value in fractions):
            raise ValueError("risk fractions must be positive")
        if not 0 < self.min_stop_pct <= self.max_stop_pct:
            raise ValueError("stop percentages are invalid")
        if self.atr_stop_multiplier <= 0 or self.lot_size <= 0:
            raise ValueError("ATR multiplier and lot size must be positive")


@dataclass(frozen=True)
class RiskPlan:
    eligible: bool
    reason: str
    entry_price: float
    stop_price: float
    stop_pct: float
    risk_per_share: float
    risk_budget: float
    shares: int
    lots: int
    position_value: float
    capital_at_risk: float
    policy: dict


def _rejected(reason: str, entry_price: float, policy: RiskPolicy,
              stop_price: float = 0.0) -> RiskPlan:
    risk_per_share = max(0.0, entry_price - stop_price)
    stop_pct = risk_per_share / entry_price * 100.0 if entry_price > 0 else 0.0
    return RiskPlan(False, reason, entry_price, stop_price, stop_pct,
                    risk_per_share, 0.0, 0, 0, 0.0, 0.0, asdict(policy))


def build_long_risk_plan(*, entry_price: float, setup_low: float | None,
                         atr: float, equity: float, open_risk: float = 0.0,
                         daily_new_risk: float = 0.0, tick_size: float = 1.0,
                         policy: RiskPolicy | None = None) -> RiskPlan:
    """Return zero size whenever a valid, affordable stop cannot be formed."""
    policy = policy or RiskPolicy()
    if entry_price <= 0 or equity <= 0 or atr <= 0 or tick_size <= 0:
        return _rejected("INVALID_INPUT", entry_price, policy)

    candidates = [entry_price - policy.atr_stop_multiplier * atr]
    if setup_low is not None and 0 < setup_low < entry_price:
        candidates.append(setup_low - tick_size)
    proposed_stop = max(candidates)
    maximum_loss_floor = entry_price * (1.0 - policy.max_stop_pct / 100.0)
    stop_price = max(proposed_stop, maximum_loss_floor)
    risk_per_share = entry_price - stop_price
    stop_pct = risk_per_share / entry_price * 100.0
    if risk_per_share <= 0:
        return _rejected("STOP_NOT_BELOW_ENTRY", entry_price, policy, stop_price)
    if stop_pct < policy.min_stop_pct:
        return _rejected("STOP_TOO_TIGHT", entry_price, policy, stop_price)

    per_trade_budget = equity * policy.risk_fraction
    remaining_open = equity * policy.max_total_open_risk_fraction - max(0.0, open_risk)
    remaining_daily = equity * policy.max_daily_new_risk_fraction - max(0.0, daily_new_risk)
    risk_budget = max(0.0, min(per_trade_budget, remaining_open, remaining_daily))
    if risk_budget <= 0:
        return _rejected("RISK_BUDGET_EXHAUSTED", entry_price, policy, stop_price)

    risk_sized_shares = floor(risk_budget / risk_per_share / policy.lot_size) * policy.lot_size
    exposure_cap = equity * policy.max_position_fraction
    exposure_sized_shares = floor(exposure_cap / entry_price / policy.lot_size) * policy.lot_size
    shares = min(risk_sized_shares, exposure_sized_shares)
    if shares < policy.lot_size:
        return _rejected("BELOW_ONE_LOT", entry_price, policy, stop_price)

    capital_at_risk = shares * risk_per_share
    return RiskPlan(
        eligible=True, reason="OK", entry_price=entry_price, stop_price=stop_price,
        stop_pct=stop_pct, risk_per_share=risk_per_share, risk_budget=risk_budget,
        shares=shares, lots=shares // policy.lot_size,
        position_value=shares * entry_price, capital_at_risk=capital_at_risk,
        policy=asdict(policy),
    )
