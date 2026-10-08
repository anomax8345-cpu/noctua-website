"""Database schema.

All timestamps are stored as ISO-8601 UTC strings. Display conversion to the
configured timezone happens in the presentation layer only.

Design notes relevant to the project goals:
  * `predictions` stores a full snapshot of model + market + edge + confidence
    at prediction time, tagged with model_version — so historical calibration
    and model comparison are possible later.
  * `prediction_results` is filled in once a fixture finishes, enabling
    calibration/Brier/log-loss without ever reading future data at predict time.
  * Market price history (`polymarket_prices`) is append-only with timestamps,
    so a price chart and 24h change can be reconstructed.
"""

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS leagues (
    id        INTEGER PRIMARY KEY,         -- API-Football league id
    name      TEXT NOT NULL,
    region    TEXT,
    country   TEXT
);

CREATE TABLE IF NOT EXISTS teams (
    id              INTEGER PRIMARY KEY,    -- API-Football team id
    name            TEXT NOT NULL,
    normalized_name TEXT,
    country         TEXT,
    logo            TEXT
);

CREATE TABLE IF NOT EXISTS fixtures (
    id            INTEGER PRIMARY KEY,      -- API-Football fixture id
    league_id     INTEGER,
    league_name   TEXT,
    season        INTEGER,
    kickoff_utc   TEXT NOT NULL,
    status        TEXT,                     -- NS, 1H, FT, etc.
    home_team_id  INTEGER,
    away_team_id  INTEGER,
    home_team     TEXT,
    away_team     TEXT,
    home_goals    INTEGER,                  -- NULL until known
    away_goals    INTEGER,
    updated_utc   TEXT
);
CREATE INDEX IF NOT EXISTS idx_fixtures_kickoff ON fixtures(kickoff_utc);

-- Elo ratings evolve over time; we keep the current rating plus split
-- home/away ratings. Historical rating changes can be reconstructed from
-- `elo_history` which the backtest engine writes chronologically.
CREATE TABLE IF NOT EXISTS team_ratings (
    team_id     INTEGER PRIMARY KEY,
    elo         REAL NOT NULL DEFAULT 1500.0,
    elo_home    REAL NOT NULL DEFAULT 1500.0,
    elo_away    REAL NOT NULL DEFAULT 1500.0,
    last_change REAL DEFAULT 0.0,
    games       INTEGER DEFAULT 0,
    updated_utc TEXT
);

CREATE TABLE IF NOT EXISTS elo_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id     INTEGER,
    fixture_id  INTEGER,
    kickoff_utc TEXT,
    elo_before  REAL,
    elo_after   REAL
);
CREATE INDEX IF NOT EXISTS idx_elo_hist_team ON elo_history(team_id, kickoff_utc);

CREATE TABLE IF NOT EXISTS team_form (
    team_id       INTEGER,
    as_of_utc     TEXT,
    window        INTEGER,                  -- 5, 10, 20
    venue         TEXT,                     -- all | home | away
    wins          INTEGER, draws INTEGER, losses INTEGER,
    gf            INTEGER, ga INTEGER,
    xg            REAL, xga REAL,           -- NULL when unavailable (never faked)
    ppg           REAL,
    PRIMARY KEY (team_id, window, venue, as_of_utc)
);

CREATE TABLE IF NOT EXISTS player_status (
    fixture_id   INTEGER,
    team_id      INTEGER,
    player_name  TEXT,
    reason       TEXT,                      -- injury | suspension | doubtful
    importance   REAL,                      -- 0..1 weight, NULL if unknown
    PRIMARY KEY (fixture_id, team_id, player_name)
);

CREATE TABLE IF NOT EXISTS predictions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc     TEXT NOT NULL,
    fixture_id        INTEGER NOT NULL,
    model_version     TEXT NOT NULL,
    market_type       TEXT NOT NULL DEFAULT '1X2',
    home_probability  REAL,
    draw_probability  REAL,
    away_probability  REAL,
    market_home       REAL,                 -- NULL when no matched market
    market_draw       REAL,
    market_away       REAL,
    edge_home         REAL,
    edge_draw         REAL,
    edge_away         REAL,
    confidence        INTEGER,
    data_quality      TEXT,                 -- HIGH | MEDIUM | LOW
    components_json   TEXT,                 -- model breakdown for the detail page
    polymarket_market_id TEXT,
    match_confidence  REAL,
    UNIQUE (fixture_id, model_version, market_type, timestamp_utc)
);
CREATE INDEX IF NOT EXISTS idx_pred_fixture ON predictions(fixture_id);

CREATE TABLE IF NOT EXISTS prediction_results (
    prediction_id  INTEGER PRIMARY KEY,
    fixture_id     INTEGER,
    outcome        TEXT,                    -- HOME | DRAW | AWAY
    predicted_prob REAL,                    -- probability the model gave to the actual outcome
    top_pick       TEXT,                    -- model's most likely outcome
    top_pick_hit   INTEGER,                 -- 1/0
    settled_utc    TEXT,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id)
);

CREATE TABLE IF NOT EXISTS polymarket_markets (
    market_id     TEXT PRIMARY KEY,
    event_id      TEXT,
    question      TEXT,
    slug          TEXT,
    outcomes_json TEXT,                     -- ["Home","Draw","Away"] etc.
    fixture_id    INTEGER,                  -- matched fixture (NULL if unmatched)
    match_confidence REAL,
    first_seen_utc TEXT,
    last_seen_utc  TEXT
);

CREATE TABLE IF NOT EXISTS polymarket_prices (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id     TEXT,
    timestamp_utc TEXT,
    outcome       TEXT,
    price         REAL,                     -- 0..1
    best_bid      REAL,
    best_ask      REAL,
    spread        REAL,
    volume        REAL,
    liquidity     REAL
);
CREATE INDEX IF NOT EXISTS idx_pm_prices ON polymarket_prices(market_id, timestamp_utc);

CREATE TABLE IF NOT EXISTS polymarket_orderbook (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id     TEXT,
    timestamp_utc TEXT,
    outcome       TEXT,
    side          TEXT,                     -- bid | ask
    price         REAL,
    size          REAL
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_utc       TEXT,
    model_version TEXT,
    start_date    TEXT,
    end_date      TEXT,
    n_matches     INTEGER,
    brier         REAL,
    log_loss      REAL,
    accuracy      REAL,
    ece           REAL,
    roi           REAL,
    max_drawdown  REAL,
    win_rate      REAL,
    avg_edge      REAL,
    detail_json   TEXT
);

-- Paper-trading ledger (Phase 4). Present now so the schema is stable.
CREATE TABLE IF NOT EXISTS paper_trades (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_utc   TEXT,
    fixture_id    INTEGER,
    market_id     TEXT,
    outcome       TEXT,
    entry_price   REAL,
    model_fair    REAL,
    size          REAL,
    status        TEXT DEFAULT 'OPEN',      -- OPEN | WIN | LOSS
    pnl           REAL,
    settled_utc   TEXT
);
"""
