"""Explicit metadata and launch gates for price bars."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class BarContract:
    scheme: str
    timeframe: str
    reference_source: str
    parity_validated: bool
    signal_eligible: bool
    reason: str = ""


INVEZGO_H1_CONTRACT = BarContract(
    scheme="invezgo_h1_live_v1",
    timeframe="60m",
    reference_source="invezgo",
    parity_validated=True,
    signal_eligible=True,
    reason="Invezgo multi-time chart; latest forming 60-minute bucket is eligible",
)

INVEZGO_DAILY_CONTRACT = BarContract(
    scheme="invezgo_daily_v1",
    timeframe="1d",
    reference_source="invezgo",
    parity_validated=True,
    signal_eligible=False,
    reason="Daily bars are retained for compatibility and are not production signals",
)




def attach_bar_contract(df: pd.DataFrame, contract: BarContract) -> pd.DataFrame:
    """Attach auditable bar provenance without changing the tabular schema."""
    df.attrs["bar_contract"] = asdict(contract)
    return df


def read_bar_contract(df: pd.DataFrame) -> BarContract | None:
    payload = df.attrs.get("bar_contract") if df is not None else None
    if not isinstance(payload, dict):
        return None
    try:
        return BarContract(**payload)
    except TypeError:
        return None


def require_price_signal_eligible(df: pd.DataFrame) -> BarContract:
    """Reject bars whose provenance has not passed the production price gate."""
    contract = read_bar_contract(df)
    if contract is None:
        raise ValueError("Price bars have no bar_contract provenance metadata")
    if not contract.signal_eligible or not contract.parity_validated:
        detail = contract.reason or "bar parity has not been validated"
        raise ValueError(f"Bar scheme {contract.scheme} is not price-signal eligible: {detail}")
    return contract
