-- Local-session actor attribution no longer requires a Google provider account.
-- Preserve all existing approval safety constraints and triggers.
PRAGMA foreign_keys = OFF;
PRAGMA legacy_alter_table = ON;
BEGIN IMMEDIATE;
CREATE TABLE conversations_local (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    title           TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    created_at_ms   INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms   INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms)
);
INSERT INTO conversations_local SELECT * FROM conversations;
DROP TABLE conversations;
ALTER TABLE conversations_local RENAME TO conversations;
CREATE INDEX ix_conversations_account_updated ON conversations(account_id, updated_at_ms DESC, id DESC);
CREATE TABLE approvals_local (
    id                         TEXT PRIMARY KEY,
    action_id                  TEXT NOT NULL,
    approval_no                INTEGER NOT NULL CHECK (approval_no >= 1),
    action_version             INTEGER NOT NULL CHECK (action_version >= 0),
    status                     TEXT NOT NULL CHECK (
        status IN ('ACTIVE', 'EXPIRED', 'CONSUMED', 'REVOKED')
    ),
    approved_by_account_id     TEXT NOT NULL,
    approved_by_display        TEXT CHECK (
        approved_by_display IS NULL
        OR length(approved_by_display) <= 200
    ),
    arguments_snapshot_json    TEXT NOT NULL CHECK (
        json_valid(arguments_snapshot_json)
        AND length(CAST(arguments_snapshot_json AS BLOB)) <= 65536
    ),
    canonical_arguments_hash   TEXT NOT NULL CHECK (length(canonical_arguments_hash) = 64),
    source_snapshot_json       TEXT NOT NULL CHECK (
        json_valid(source_snapshot_json)
        AND length(CAST(source_snapshot_json AS BLOB)) <= 65536
    ),
    source_snapshot_hash       TEXT NOT NULL CHECK (length(source_snapshot_hash) = 64),
    policy_version             TEXT NOT NULL,
    tool_schema_version        TEXT NOT NULL,
    idempotency_key            TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) = 64),
    recovery_fingerprint       TEXT NOT NULL CHECK (length(recovery_fingerprint) = 64),
    approved_at_ms             INTEGER NOT NULL CHECK (approved_at_ms >= 0),
    expires_at_ms              INTEGER NOT NULL CHECK (expires_at_ms > approved_at_ms),
    consumed_at_ms             INTEGER CHECK (
        consumed_at_ms IS NULL OR consumed_at_ms >= approved_at_ms
    ),
    FOREIGN KEY (action_id) REFERENCES actions(id) ON DELETE CASCADE,
    UNIQUE (action_id, approval_no)
);
INSERT INTO approvals_local SELECT * FROM approvals;
DROP TABLE approvals;
ALTER TABLE approvals_local RENAME TO approvals;
CREATE UNIQUE INDEX uq_approvals_one_active_per_action ON approvals(action_id) WHERE status = 'ACTIVE';
CREATE INDEX ix_approvals_expiry ON approvals(status, expires_at_ms) WHERE status = 'ACTIVE';
CREATE TRIGGER trg_approvals_active_action_guard_insert
BEFORE INSERT ON approvals
WHEN NEW.status = 'ACTIVE'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        JOIN runs AS r ON r.id = p.run_id
        WHERE a.id = NEW.action_id
          AND a.status = 'APPROVED'
          AND a.effect_type <> 'READ'
          AND a.version = NEW.action_version
          AND p.status = 'WAITING_APPROVAL'
          AND p.review_status = 'PASSED'
          AND p.review_disposition = 'PASS'
          AND p.revision_no = (SELECT MAX(p2.revision_no) FROM plans AS p2 WHERE p2.run_id=p.run_id)
          AND r.status IN ('WAITING_APPROVAL', 'VERIFYING')
          AND NOT EXISTS (
              SELECT 1
              FROM execution_attempts AS prior_ea
              JOIN approvals AS prior_ap ON prior_ap.id = prior_ea.approval_id
              JOIN actions AS prior_a ON prior_a.id = prior_ap.action_id
              JOIN plans AS prior_p ON prior_p.id = prior_a.plan_id
              WHERE prior_p.run_id = p.run_id
                AND prior_ea.status = 'UNKNOWN_RESULT'
          )
    ) THEN RAISE(ABORT, 'NFR019_ACTIVE_APPROVAL_ACTION') END;
END;
CREATE TRIGGER trg_approvals_active_action_guard_update
BEFORE UPDATE OF status, action_id, action_version ON approvals
WHEN NEW.status = 'ACTIVE'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        JOIN runs AS r ON r.id = p.run_id
        WHERE a.id = NEW.action_id
          AND a.status = 'APPROVED'
          AND a.effect_type <> 'READ'
          AND a.version = NEW.action_version
          AND p.status = 'WAITING_APPROVAL'
          AND p.review_status = 'PASSED'
          AND p.review_disposition = 'PASS'
          AND p.revision_no = (SELECT MAX(p2.revision_no) FROM plans AS p2 WHERE p2.run_id=p.run_id)
          AND r.status IN ('WAITING_APPROVAL', 'VERIFYING')
          AND NOT EXISTS (
              SELECT 1
              FROM execution_attempts AS prior_ea
              JOIN approvals AS prior_ap ON prior_ap.id = prior_ea.approval_id
              JOIN actions AS prior_a ON prior_a.id = prior_ap.action_id
              JOIN plans AS prior_p ON prior_p.id = prior_a.plan_id
              WHERE prior_p.run_id = p.run_id
                AND prior_ea.status = 'UNKNOWN_RESULT'
          )
    ) THEN RAISE(ABORT, 'NFR019_ACTIVE_APPROVAL_ACTION') END;
END;
CREATE TRIGGER trg_approvals_lineage_immutable
BEFORE UPDATE OF action_id, action_version, approval_no ON approvals
WHEN NEW.action_id IS NOT OLD.action_id
  OR NEW.action_version IS NOT OLD.action_version
  OR NEW.approval_no IS NOT OLD.approval_no
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_APPROVAL_LINEAGE_IMMUTABLE');
END;
COMMIT;
PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
