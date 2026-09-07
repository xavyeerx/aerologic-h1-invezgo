# EDR: Invezgo Intrabar H1 Migration

## Context and decision

Production price signals use Invezgo `analysis/chart/multi-time/{code}` with
`timeframe=60`. Daily chart data is no longer signal-eligible. The latest forming
H1 bar is signal-eligible so intrabar Supertrend breakout can alert without waiting
for bar close.

## Bar contract

- Contract: `invezgo_h1_live_v1`, timeframe `60m`.
- Invezgo timestamps such as `09:00Z` are treated as IDX exchange wall-clock bucket
  labels and localized directly to `Asia/Jakarta`; they are not shifted from UTC.
- The current incomplete bucket is retained. Its closed/open state is recorded as
  `bar_closed` in signal events for auditability.
- The scheduler runs every five minutes during IDX sessions. Price signals use the
  latest available H1 bucket, including a forming candle.
- Realtime screener prices select candidates only. They never override the H1 close
  used by Supertrend or signal decisions.

## Indicator semantics

- Supertrend uses TradingView-compatible Wilder RMA ATR, period 10, multiplier 3.
- Invezgo pre-open (`08:xx`) and closing-auction (`16:xx`) buckets are excluded
  from indicator history to match TradingView's IDX regular-session H1 bars.
- Because multi-time history is EOD-delayed, the realtime screener close is used
  only to evaluate a live cross against the last regular-H1 Supertrend resistance.
- Initialization is at ATR bar `period - 1`, initially on the bearish upper band,
  matching `ta.supertrend`; project direction uses `+1` bullish and `-1` bearish.
- `return20_pct` means 20 H1 bars, and market momentum means five H1 bars.
- Daily aggregated turnover remains a liquidity/risk feature, not a signal timeframe.
- Existing daily alert history remains in place as an operational risk cap and to
  prevent duplicate alerts after deployment.

## Risks and validation boundary

Thresholds inherited from the Daily strategy are migration defaults, not evidence of
H1 strategy quality. Forward validation and historical H1 backtesting are required.
Intrabar signals may repaint before close. Exact chart parity also depends on
TradingView using an equivalent IDX feed, session, auction inclusion, corporate-action
adjustment, and comparing both platforms at the same instant.
