-- Identidades externas y recuperación de importaciones; no altera ofertas existentes.
CREATE TABLE IF NOT EXISTS external_jobs (
    source_name TEXT NOT NULL,
    external_id TEXT NOT NULL,
    job_id BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    content_hash TEXT,
    material_hash TEXT NOT NULL,
    scraped_at TEXT,
    publish_date_text TEXT,
    first_received_at TEXT NOT NULL,
    last_received_at TEXT NOT NULL,
    PRIMARY KEY (source_name, external_id)
);
CREATE INDEX IF NOT EXISTS external_jobs_job ON external_jobs(job_id);
CREATE TABLE IF NOT EXISTS apify_import_runs (
    run_id TEXT PRIMARY KEY,
    dataset_id TEXT,
    actor_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 1,
    cursor INTEGER NOT NULL DEFAULT 0,
    dataset_hash TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    result TEXT NOT NULL,
    error_code TEXT,
    task_run_id BIGINT REFERENCES task_runs(id)
);
