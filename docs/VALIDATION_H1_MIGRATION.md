# Validation Report: H1 Migration

## Verified

- Live Invezgo request for BBCA `timeframe=60` returned 311 unique H1 rows over the
  configured 45-day request window.
- Parsed timestamps retain `Asia/Jakarta` exchange labels and do not collapse to one
  row per date.
- Latest live sample produced a finite Supertrend value and direction.
- Incomplete current H1 bars are excluded by an automated test.
- Scheduler slots cover irregular Monday-Thursday and Friday IDX buckets.
- Daily legacy bars are rejected by the production signal eligibility gate.
- Automated suite: 52 tests and 4 subtests passed at migration time, including the
  TradingView-compatible first-ATR-bar Supertrend initialization contract.

## Not yet proven

- TradingView visual parity has not been measured against an exported TradingView
  OHLC/Supertrend fixture for the exact same symbol, feed, and session.
- Daily-derived signal thresholds have not yet been recalibrated or backtested on H1.
- The weekday gate does not yet consume an official IDX holiday calendar.

These unknowns affect strategy validity and exact cross-provider parity, but not the
verified ability to fetch, preserve, close-gate, and calculate Supertrend on H1 bars.
