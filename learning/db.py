# ============================================================
# LEARNING / DB.PY — PostgreSQL connection + schema
# ============================================================
# Menyimpan signal history, learning insights, dan adaptive config.
# Bot berjalan normal tanpa DB (graceful degradation).
#
# Setup Railway:
#   1. Railway dashboard → project → "+ New" → "Database" → PostgreSQL
#   2. Klik PostgreSQL service → "Connect" → copy DATABASE_URL
#   3. Set env var DATABASE_URL di service utama
# ============================================================

import os
import logging
import psycopg2

logger = logging.getLogger(__name__)

# Railway otomatis set ini saat PostgreSQL addon aktif
DATABASE_URL = os.getenv('DATABASE_URL', '')

# Schema SQL — semua tabel yang dibutuhkan learning system
_SCHEMA_SQL = """
-- ── Signal History ──────────────────────────────────────────────────
-- Setiap sinyal yang dikirim ke Telegram dicatat di sini beserta
-- semua kondisi teknikal saat sinyal terjadi.
CREATE TABLE IF NOT EXISTS signal_history (
    signal_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker           VARCHAR(20)  NOT NULL,
    signal_type      VARCHAR(20)  NOT NULL,   -- STRONG_BUY / ACCUMULATION / EARLY_ENTRY / BULL_DIV
    sent_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Harga & target
    entry_price      FLOAT,
    tp1_price        FLOAT,                   -- entry + 1.0×ATR
    tp2_price        FLOAT,                   -- resistance atau entry + 2.5×ATR
    tp2_source       VARCHAR(15),             -- 'RESISTANCE' atau 'ATR'
    sl_price         FLOAT,                   -- entry × 0.95

    -- Kondisi teknikal saat sinyal (fitur pembelajaran)
    score            INTEGER,
    adx              FLOAT,
    volume_ratio     FLOAT,
    stoch_k          FLOAT,
    macd_bullish     BOOLEAN,
    obv_bullish      BOOLEAN,
    market_regime    VARCHAR(10),             -- BULL / BEAR / SIDEWAYS
    bars_since_breakout    INTEGER,           -- candle sejak supertrend flip bullish
    price_vs_supertrend_pct FLOAT,            -- % harga di atas supertrend line
    ihsg_adx         FLOAT,                   -- ADX IHSG composite (^JKSE)
    ihsg_momentum_5d_pct FLOAT,               -- % change IHSG 5 hari terakhir
    prev_signal_outcome  VARCHAR(20),         -- outcome sinyal sebelumnya untuk ticker ini
    atr_pct          FLOAT,                   -- ATR relatif terhadap harga (volatility)
    correction_depth_pct FLOAT,               -- kedalaman koreksi (untuk EARLY_ENTRY)

    -- Outcome (diisi oleh outcome_checker.py setelah N hari)
    outcome_1d       VARCHAR(20)  DEFAULT 'PENDING',
    outcome_3d       VARCHAR(20)  DEFAULT 'PENDING',
    outcome_5d       VARCHAR(20)  DEFAULT 'PENDING',
    outcome_10d      VARCHAR(20)  DEFAULT 'PENDING',   -- FINAL outcome
    tp1_hit          BOOLEAN      DEFAULT FALSE,
    tp2_hit          BOOLEAN      DEFAULT FALSE,
    max_gain_pct     FLOAT,
    max_drawdown_pct FLOAT,
    days_to_tp1      INTEGER,
    days_to_tp2      INTEGER,
    days_to_outcome  INTEGER,
    evaluation_done  BOOLEAN      DEFAULT FALSE
);

-- Index untuk query yang sering digunakan
CREATE INDEX IF NOT EXISTS idx_signal_ticker      ON signal_history (ticker);
CREATE INDEX IF NOT EXISTS idx_signal_sent_at     ON signal_history (sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_eval_done   ON signal_history (evaluation_done);
CREATE INDEX IF NOT EXISTS idx_signal_type        ON signal_history (signal_type);

-- ── Learning Insights ────────────────────────────────────────────────
-- Setiap kali learning engine menemukan pola valid (n>=30, p<0.05),
-- hasilnya dicatat di sini sebagai audit trail.
CREATE TABLE IF NOT EXISTS learning_insights (
    insight_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    insight_type  VARCHAR(30),    -- WEIGHT_ADJUST / PATTERN_FOUND / REGIME_CHANGE
    description   TEXT,
    feature       VARCHAR(50),    -- fitur yang berubah (ex: 'min_adx')
    old_value     FLOAT,
    new_value     FLOAT,
    confidence    FLOAT,          -- 0.0 – 1.0 (dari p-value)
    sample_size   INTEGER         -- jumlah sinyal yang jadi dasar insight
);

-- ── Adaptive Config ──────────────────────────────────────────────────
-- Threshold dinamis yang bisa diubah oleh learning engine.
-- Bot membaca tabel ini setiap scan agar threshold selalu terkini.
CREATE TABLE IF NOT EXISTS adaptive_config (
    key          VARCHAR(50) PRIMARY KEY,
    value        FLOAT       NOT NULL,
    default_val  FLOAT       NOT NULL,
    updated_at   TIMESTAMPTZ DEFAULT NOW(),
    description  TEXT
);
"""

_DEFAULT_CONFIG = [
    ('min_adx',                     25.0, 25.0, 'Minimum ADX untuk semua sinyal'),
    ('min_volume_ratio',             1.5,  1.5,  'Minimum volume ratio (vs avg 20d)'),
    ('max_price_vs_supertrend_pct',  8.0,  8.0,  'Max % di atas supertrend (terlalu extended)'),
    ('max_bars_since_breakout',     15.0, 15.0,  'Max candle sejak breakout (stale breakout)'),
    ('buy_score_threshold',         70.0, 70.0,  'Min score untuk STRONG BUY'),
    ('acc_score_threshold',         55.0, 55.0,  'Min score untuk ACCUMULATION'),
    ('min_ihsg_momentum_5d',        -3.0, -3.0,  'Min IHSG momentum 5d (bawah ini = suspend sinyal)'),
    ('obv_weight_bonus',             1.0,  1.0,  'Bonus multiplier jika OBV bullish (1.0 = no change)'),
]


def _fix_url(url: str) -> str:
    """Railway kadang pakai 'postgres://' — psycopg2 perlu 'postgresql://'"""
    return url.replace('postgres://', 'postgresql://', 1) if url.startswith('postgres://') else url


def get_connection():
    """
    Buka koneksi ke PostgreSQL.
    Return None jika DATABASE_URL tidak di-set (graceful degradation).
    """
    if not DATABASE_URL:
        return None
    try:
        conn = psycopg2.connect(_fix_url(DATABASE_URL))
        conn.autocommit = False
        return conn
    except Exception as e:
        logger.warning(f"[LearningDB] Koneksi gagal: {e}")
        return None


def init_db() -> bool:
    """
    Buat tabel dan isi default adaptive_config jika belum ada.
    Dipanggil sekali saat scheduler start.
    Return True jika sukses, False jika tidak ada DB.
    """
    conn = get_connection()
    if not conn:
        logger.warning("[LearningDB] DATABASE_URL tidak di-set — learning system dinonaktifkan")
        return False

    try:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)
            # Insert default config (skip jika sudah ada)
            for key, val, default, desc in _DEFAULT_CONFIG:
                cur.execute("""
                    INSERT INTO adaptive_config (key, value, default_val, description)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (key) DO NOTHING
                """, (key, val, default, desc))
        conn.commit()
        logger.info("[LearningDB] ✅ Database siap (tabel OK, config default selesai)")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[LearningDB] Init gagal: {e}")
        return False
    finally:
        conn.close()


def get_adaptive_config() -> dict:
    """
    Ambil semua adaptive config dari DB.
    Return dict kosong jika DB tidak tersedia (bot pakai default dari settings.py).
    """
    conn = get_connection()
    if not conn:
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT key, value FROM adaptive_config")
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}
    except Exception as e:
        logger.warning(f"[LearningDB] Gagal ambil adaptive config: {e}")
        return {}
    finally:
        conn.close()


def update_adaptive_config(key: str, new_value: float, old_value: float,
                            description: str = '', confidence: float = 0.0,
                            sample_size: int = 0) -> bool:
    """
    Update satu adaptive config + catat sebagai learning insight.
    Hanya dipanggil oleh learning_engine.py setelah validasi statistik.
    """
    conn = get_connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            # Update config
            cur.execute("""
                UPDATE adaptive_config
                SET value = %s, updated_at = NOW()
                WHERE key = %s
            """, (new_value, key))

            # Catat insight
            cur.execute("""
                INSERT INTO learning_insights
                    (insight_type, description, feature, old_value, new_value, confidence, sample_size)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, ('WEIGHT_ADJUST', description, key, old_value, new_value, confidence, sample_size))

        conn.commit()
        logger.info(f"[LearningDB] Config '{key}' diupdate: {old_value} → {new_value} "
                    f"(confidence: {confidence:.2f}, n={sample_size})")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[LearningDB] Gagal update config: {e}")
        return False
    finally:
        conn.close()


def is_available() -> bool:
    """Cek apakah DB connection tersedia"""
    return bool(DATABASE_URL)
