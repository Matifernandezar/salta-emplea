-- Migración 1. La base comienza vacía: nunca contiene ofertas de demostración.
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company TEXT,
    location TEXT,
    modality TEXT CHECK (modality IS NULL OR modality IN ('presencial', 'híbrida', 'remota')),
    sector TEXT,
    schedule TEXT,
    contract_type TEXT,
    requirements TEXT,
    description TEXT,
    salary_amount TEXT,
    salary_currency TEXT,
    salary_period TEXT,
    salary_source_evidence TEXT,
    source_url TEXT,
    source_canonical_url TEXT UNIQUE,
    source_name TEXT,
    original_text TEXT,
    image_path TEXT,
    application_url TEXT,
    original_date TEXT,
    collected_at TEXT NOT NULL,
    last_checked_at TEXT,
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'archived', 'expired')),
    flags TEXT NOT NULL DEFAULT '[]',
    uncertain_fields TEXT NOT NULL DEFAULT '[]',
    approved_at TEXT,
    approved_by TEXT,
    review_needed INTEGER NOT NULL DEFAULT 0 CHECK (review_needed IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((salary_amount IS NULL AND salary_currency IS NULL AND salary_period IS NULL)
        OR (salary_amount IS NOT NULL AND salary_currency IS NOT NULL AND salary_period IS NOT NULL AND salary_source_evidence IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS jobs_public ON jobs(status, collected_at DESC);
CREATE INDEX IF NOT EXISTS jobs_expiration ON jobs(expires_at);

CREATE TABLE IF NOT EXISTS provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_url TEXT,
    source_name TEXT,
    original_text TEXT,
    image_path TEXT,
    payload TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    UNIQUE(job_id, fingerprint)
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT 'manual',
    frequency_hours INTEGER NOT NULL DEFAULT 24 CHECK (frequency_hours > 0),
    status TEXT NOT NULL DEFAULT 'pending',
    last_result TEXT,
    last_run_at TEXT,
    terms_url TEXT,
    terms_checked_at TEXT,
    authorized INTEGER NOT NULL DEFAULT 0 CHECK (authorized IN (0, 1))
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES jobs(id),
    reason TEXT NOT NULL,
    contact TEXT,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    locality TEXT,
    sector TEXT,
    modality TEXT,
    frequency TEXT NOT NULL DEFAULT 'weekly' CHECK (frequency IN ('daily', 'weekly')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'unsubscribed')),
    token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confirmed_at TEXT,
    last_sent_at TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    subscriber_id INTEGER REFERENCES subscribers(id),
    job_ids TEXT NOT NULL DEFAULT '[]',
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    idempotency_key TEXT NOT NULL UNIQUE,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    first_attempt_at TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    last_error TEXT
);
CREATE INDEX IF NOT EXISTS outbox_pending ON outbox(status, next_attempt_at);
CREATE TABLE IF NOT EXISTS deliveries (
    subscriber_id INTEGER NOT NULL REFERENCES subscribers(id),
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    outbox_id INTEGER REFERENCES outbox(id),
    UNIQUE(subscriber_id, job_id)
);
CREATE TABLE IF NOT EXISTS ads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL DEFAULT 'Publicidad',
    image_url TEXT,
    link_url TEXT NOT NULL,
    placement TEXT NOT NULL DEFAULT 'home',
    starts_at TEXT,
    ends_at TEXT,
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1))
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_id INTEGER,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rate_limits (
    key TEXT PRIMARY KEY,
    count INTEGER NOT NULL DEFAULT 0,
    reset_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    detail TEXT
);

INSERT OR IGNORE INTO schema_migrations(version, applied_at)
VALUES (1, strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'));
PRAGMA user_version = 1;
