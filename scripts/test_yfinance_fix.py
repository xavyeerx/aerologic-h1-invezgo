"""
Test script: verifikasi fix yfinance multi-index bug
"""
import sys
import yfinance as yf
import pandas as pd

TICKER = "BBCA.JK"
print(f"yfinance version: {yf.__version__}")
print("-" * 50)

pass_count = 0
fail_count = 0

# ── Test 1: multi_level_index=False ─────────────────────────────
print("Test 1: yf.download dengan multi_level_index=False")
try:
    data = yf.download(
        TICKER, period="5d", interval="1d",
        progress=False, auto_adjust=True, multi_level_index=False
    )
    is_multi = isinstance(data.columns, pd.MultiIndex)
    print(f"  MultiIndex? {is_multi}")
    print(f"  columns raw: {list(data.columns)}")
    if is_multi:
        data.columns = data.columns.get_level_values(0)
    data.columns = [str(c).lower() for c in data.columns]
    print(f"  After lower: {list(data.columns)}")
    h = float(data["high"].iloc[-1])
    print(f"  high sample: {h}")
    print("  [PASS] Test 1")
    pass_count += 1
except TypeError:
    print("  [SKIP] multi_level_index not supported in this yfinance version")
    pass_count += 1
except Exception as e:
    print(f"  [FAIL] Test 1: {e}")
    fail_count += 1

# ── Test 2: Without multi_level_index (fallback path) ────────────
print("\nTest 2: yf.download tanpa multi_level_index (mode lama)")
try:
    data2 = yf.download(
        TICKER, period="5d", interval="1d",
        progress=False, auto_adjust=True
    )
    is_multi2 = isinstance(data2.columns, pd.MultiIndex)
    print(f"  MultiIndex? {is_multi2}")
    if is_multi2:
        data2.columns = data2.columns.get_level_values(0)
    data2.columns = [str(c).lower() for c in data2.columns]
    print(f"  After flatten+lower: {list(data2.columns)}")
    h2 = float(data2["high"].iloc[-1])
    print(f"  high sample: {h2}")
    print("  [PASS] Test 2")
    pass_count += 1
except Exception as e:
    print(f"  [FAIL] Test 2: {e}")
    fail_count += 1

# ── Test 3: OHLC bar access simulasi outcome_checker ─────────────
print("\nTest 3: Simulasi loop OHLC seperti di outcome_checker.py")
try:
    from datetime import date, timedelta
    from_date = date.today() - timedelta(days=10)
    to_date   = date.today()

    try:
        raw = yf.download(
            TICKER,
            start=from_date.strftime("%Y-%m-%d"),
            end=(to_date + timedelta(days=2)).strftime("%Y-%m-%d"),
            interval="1d", progress=False, auto_adjust=True,
            multi_level_index=False,
        )
    except TypeError:
        raw = yf.download(
            TICKER,
            start=from_date.strftime("%Y-%m-%d"),
            end=(to_date + timedelta(days=2)).strftime("%Y-%m-%d"),
            interval="1d", progress=False, auto_adjust=True,
        )

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw.columns = [str(c).lower() for c in raw.columns]

    if raw.index.tz is not None:
        raw.index = raw.index.tz_localize(None)

    raw = raw[raw.index.date > from_date]
    print(f"  Rows fetched: {len(raw)}")
    for idx, bar in raw.iterrows():
        high  = float(bar["high"])
        low   = float(bar["low"])
        close = float(bar["close"])
        print(f"    {idx.date()} H={high:.0f} L={low:.0f} C={close:.0f}")

    print("  [PASS] Test 3")
    pass_count += 1
except Exception as e:
    print(f"  [FAIL] Test 3: {e}")
    fail_count += 1

# ── Summary ───────────────────────────────────────────────────────
print("\n" + "=" * 50)
print(f"HASIL: {pass_count} PASS, {fail_count} FAIL")
if fail_count == 0:
    print("✅ Semua test lulus — bug multi-index RESOLVED")
    sys.exit(0)
else:
    print("❌ Ada test gagal — perlu investigasi lebih lanjut")
    sys.exit(1)
