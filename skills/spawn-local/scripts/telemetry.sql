CREATE TABLE IF NOT EXISTS telemetry_events (
    token TEXT NOT NULL, event TEXT NOT NULL, at_ms INTEGER NOT NULL,
    PRIMARY KEY(token,event)
);
CREATE TABLE IF NOT EXISTS telemetry_labels (
    token TEXT PRIMARY KEY, kind TEXT, cohort TEXT, base_sha TEXT
);
CREATE TABLE IF NOT EXISTS telemetry_usage (
    token TEXT PRIMARY KEY, input_tokens INTEGER, cached_tokens INTEGER,
    output_tokens INTEGER, inference_ms INTEGER
);
CREATE TRIGGER IF NOT EXISTS telemetry_reserve AFTER INSERT ON attempts BEGIN
    INSERT OR IGNORE INTO telemetry_events VALUES(NEW.token,'reserved',CAST((julianday('now')-2440587.5)*86400000 AS INTEGER));
END;
CREATE TRIGGER IF NOT EXISTS telemetry_worker_bind AFTER UPDATE OF task ON attempts
WHEN OLD.task IS NULL AND NEW.task IS NOT NULL BEGIN
    INSERT OR IGNORE INTO telemetry_events VALUES(NEW.token,'bound',CAST((julianday('now')-2440587.5)*86400000 AS INTEGER));
END;
CREATE TRIGGER IF NOT EXISTS telemetry_worker_done AFTER UPDATE OF outcome ON attempts
WHEN OLD.outcome IS NULL AND NEW.outcome IS NOT NULL BEGIN
    INSERT OR IGNORE INTO telemetry_events VALUES(NEW.token,'finished',CAST((julianday('now')-2440587.5)*86400000 AS INTEGER));
END;
CREATE TRIGGER IF NOT EXISTS telemetry_review_reserve AFTER INSERT ON reviews BEGIN
    INSERT OR IGNORE INTO telemetry_events VALUES(NEW.token,'reserved',CAST((julianday('now')-2440587.5)*86400000 AS INTEGER));
END;
CREATE TRIGGER IF NOT EXISTS telemetry_review_bind AFTER UPDATE OF task ON reviews
WHEN OLD.task IS NULL AND NEW.task IS NOT NULL BEGIN
    INSERT OR IGNORE INTO telemetry_events VALUES(NEW.token,'bound',CAST((julianday('now')-2440587.5)*86400000 AS INTEGER));
END;
CREATE TRIGGER IF NOT EXISTS telemetry_review_done AFTER UPDATE OF report,infra ON reviews
WHEN OLD.report IS NULL AND OLD.infra IS NULL AND (NEW.report IS NOT NULL OR NEW.infra IS NOT NULL) BEGIN
    INSERT OR IGNORE INTO telemetry_events VALUES(NEW.token,'finished',CAST((julianday('now')-2440587.5)*86400000 AS INTEGER));
END;

CREATE TABLE IF NOT EXISTS telemetry_t3 (token TEXT PRIMARY KEY, metadata TEXT NOT NULL);
