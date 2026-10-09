"""Database schema (tennis).

Timestamps are ISO-8601 UTC strings. Tennis is a 2-outcome sport (no draw), so
predictions store p1/p2 probabilities only. Player ratings are kept overall AND
per surface, which is essential in tennis.
"""

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS players (
    id              TEXT PRIMARY KEY,         -- provider player key
    name            TEXT NOT NULL,
    normalized_name TEXT,
    country         TEXT,
    tour            TEXT                      -- ATP | WTA | ...
);

CREATE TABLE IF NOT EXISTS fixtures (
    id            TEXT PRIMARY KEY,           -- provider fixture/event key
    tour          TEXT,
    tournament    TEXT,
    round         TEXT,
    surface       TEXT,                       -- Hard|Clay|Grass|Carpet|NULL
    best_of       INTEGER,                    -- 3 or 5
    kickoff_utc   TEXT NOT NULL,
    status        TEXT,
    p1_id         TEXT, p2_id TEXT,
    p1_name       TEXT, p2_name TEXT,
    winner        TEXT,                        -- 'p1' | 'p2' | NULL
    score         TEXT,
    updated_utc   TEXT
);
CREATE INDEX IF NOT EXISTS idx_fixtures_kickoff ON fixtures(kickoff_utc);

-- Elo overall + per surface. elo_surface_json holds {"Hard":1800, "Clay":1720}.
CREATE TABLE IF NOT EXISTS player_ratings (
    player_id        TEXT PRIMARY KEY,
    elo              REAL NOT NULL DEFAULT 1500.0,
    elo_surface_json TEXT DEFAULT '{}',
    last_change      REAL DEFAULT 0.0,
    matches          INTEGER DEFAULT 0,
    updated_utc      TEXT
);

CREATE TABLE IF NOT EXISTS player_form (
    player_id   TEXT,
    as_of_utc   TEXT,
    window      INTEGER,
    surface     TEXT,                          -- all | Hard | Clay | Grass | Carpet
    played      INTEGER, wins INTEGER, losses INTEGER,
    win_pct     REAL,
    form_string TEXT,
    PRIMARY KEY (player_id, window, surface, as_of_utc)
);

CREATE TABLE IF NOT EXISTS h2h (
    p1_id       TEXT, p2_id TEXT,
    p1_wins     INTEGER, p2_wins INTEGER,
    last_meeting_utc TEXT,
    PRIMARY KEY (p1_id, p2_id)
);

CREATE TABLE IF NOT EXISTS predictions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc     TEXT NOT NULL,
    fixture_id        TEXT NOT NULL,
    model_version     TEXT NOT NULL,
    market_type       TEXT NOT NULL DEFAULT 'MATCH_WINNER',
    p1_probability    REAL,
    p2_probability    REAL,
    market_p1         REAL,
    market_p2         REAL,
    edge_p1           REAL,
    edge_p2           REAL,
    confidence        INTEGER,
    data_quality      TEXT,
    components_json   TEXT,
    polymarket_market_id TEXT,
    match_confidence  REAL,
    UNIQUE (fixture_id, model_version, market_type, timestamp_utc)
);
CREATE INDEX IF NOT EXISTS idx_pred_fixture ON predictions(fixture_id);

CREATE TABLE IF NOT EXISTS prediction_results (
    prediction_id  INTEGER PRIMARY KEY,
    fixture_id     TEXT,
    outcome        TEXT,                        -- 'p1' | 'p2'
    predicted_prob REAL,                        -- prob model gave to the actual winner
    top_pick       TEXT,
    top_pick_hit   INTEGER,
    settled_utc    TEXT,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);

CREATE TABLE IF NOT EXISTS polymarket_markets (
    market_id     TEXT PRIMARY KEY,
    event_id      TEXT,
    question      TEXT,
    slug          TEXT,
    outcomes_json TEXT,
    fixture_id    TEXT,
    match_confidence REAL,
    first_seen_utc TEXT,
    last_seen_utc  TEXT
);

CREATE TABLE IF NOT EXISTS polymarket_prices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id     TEXT,
    timestamp_utc TEXT,
    outcome       TEXT,
    price         REAL,
    best_bid      REAL,
    best_ask      REAL,
    spread        REAL,
    volume        REAL,
    liquidity     REAL
);
CREATE INDEX IF NOT EXISTS idx_pm_prices ON polymarket_prices(market_id, timestamp_utc);

CREATE TABLE IF NOT EXISTS backtest_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_utc       TEXT,
    model_version TEXT,
    start_date    TEXT, end_date TEXT,
    n_matches     INTEGER,
    brier REAL, log_loss REAL, accuracy REAL, ece REAL,
    roi REAL, max_drawdown REAL, win_rate REAL, avg_edge REAL,
    detail_json   TEXT
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc   TEXT,
    fixture_id    TEXT,
    market_id     TEXT,
    outcome       TEXT,
    entry_price   REAL,
    model_fair    REAL,
    size          REAL,
    status        TEXT DEFAULT 'OPEN',
    pnl           REAL,
    settled_utc   TEXT
);
"""
