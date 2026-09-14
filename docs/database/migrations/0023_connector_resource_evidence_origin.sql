-- Replace the provider-specific Evidence origin with the connector-neutral domain value.
PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

CREATE TABLE evidence_connector_origin (
    id                TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL,
    origin_type       TEXT NOT NULL CHECK (
        origin_type IN ('CONNECTOR_RESOURCE', 'USER_MESSAGE', 'DERIVED')
    ),
    resource_ref_id   TEXT,
    message_id        TEXT,
    kind              TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 50),
    excerpt           TEXT NOT NULL CHECK (
        length(CAST(excerpt AS BLOB)) <= 8192
    ),
    locator_json      TEXT CHECK (
        locator_json IS NULL
        OR (
            json_valid(locator_json)
            AND length(CAST(locator_json AS BLOB)) <= 16384
        )
    ),
    created_at_ms     INTEGER NOT NULL CHECK (created_at_ms >= 0),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (resource_ref_id) REFERENCES resource_refs(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CHECK (
        (
            origin_type = 'CONNECTOR_RESOURCE'
            AND resource_ref_id IS NOT NULL
            AND message_id IS NULL
        )
        OR
        (
            origin_type = 'USER_MESSAGE'
            AND resource_ref_id IS NULL
            AND message_id IS NOT NULL
        )
        OR
        (
            origin_type = 'DERIVED'
            AND resource_ref_id IS NULL
            AND message_id IS NULL
        )
    )
);

INSERT INTO evidence_connector_origin (
    id,
    run_id,
    origin_type,
    resource_ref_id,
    message_id,
    kind,
    excerpt,
    locator_json,
    created_at_ms
)
SELECT
    id,
    run_id,
    CASE
        WHEN origin_type = 'GOOGLE_RESOURCE' THEN 'CONNECTOR_RESOURCE'
        ELSE origin_type
    END,
    resource_ref_id,
    message_id,
    kind,
    excerpt,
    locator_json,
    created_at_ms
FROM evidence;

DROP TRIGGER trg_plan_aggregate_action_evidence_insert;
DROP TRIGGER trg_plan_aggregate_action_evidence_update;
DROP TRIGGER trg_plan_aggregate_message_conversation_update;
DROP TRIGGER trg_plan_aggregate_run_conversation_update;
DROP TRIGGER trg_plan_aggregate_action_plan_update;
DROP TRIGGER trg_plan_aggregate_evidence_insert;
DROP TRIGGER trg_plan_aggregate_evidence_update;
DROP TRIGGER trg_plan_aggregate_plan_run_update;
DROP TRIGGER trg_plan_aggregate_resource_run_update;
DROP TABLE evidence;
ALTER TABLE evidence_connector_origin RENAME TO evidence;

CREATE INDEX ix_evidence_run_created
    ON evidence(run_id, created_at_ms);

CREATE INDEX ix_evidence_resource_ref
    ON evidence(resource_ref_id)
    WHERE resource_ref_id IS NOT NULL;

CREATE INDEX ix_evidence_message
    ON evidence(message_id)
    WHERE message_id IS NOT NULL;

CREATE TRIGGER trg_plan_aggregate_action_evidence_insert
BEFORE INSERT ON action_evidence
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        JOIN evidence AS e ON e.id = NEW.evidence_id
        WHERE a.id = NEW.action_id
          AND e.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action evidence must belong to plan run') END;
END;

CREATE TRIGGER trg_plan_aggregate_action_evidence_update
BEFORE UPDATE OF action_id, evidence_id ON action_evidence
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        JOIN evidence AS e ON e.id = NEW.evidence_id
        WHERE a.id = NEW.action_id
          AND e.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action evidence must belong to plan run') END;
END;

CREATE TRIGGER trg_plan_aggregate_message_conversation_update
BEFORE UPDATE OF conversation_id ON messages
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM evidence AS e
        JOIN runs AS r ON r.id = e.run_id
        WHERE e.origin_type = 'USER_MESSAGE'
          AND e.message_id = OLD.id
          AND r.conversation_id <> NEW.conversation_id
    ) THEN RAISE(ABORT, 'message conversation update would break evidence links') END;
END;

CREATE TRIGGER trg_plan_aggregate_run_conversation_update
BEFORE UPDATE OF conversation_id ON runs
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM evidence AS e
        JOIN messages AS m ON m.id = e.message_id
        WHERE e.origin_type = 'USER_MESSAGE'
          AND e.run_id = OLD.id
          AND m.conversation_id <> NEW.conversation_id
    ) THEN RAISE(ABORT, 'run conversation update would break evidence links') END;
END;

CREATE TRIGGER trg_plan_aggregate_action_plan_update
BEFORE UPDATE OF plan_id, target_resource_ref_id ON actions
BEGIN
    SELECT CASE WHEN NEW.target_resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM plans AS p
        JOIN resource_refs AS rr ON rr.id = NEW.target_resource_ref_id
        WHERE p.id = NEW.plan_id AND rr.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action target resource_ref must belong to plan run') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_evidence AS ae
        JOIN evidence AS e ON e.id = ae.evidence_id
        JOIN plans AS p ON p.id = NEW.plan_id
        WHERE ae.action_id = OLD.id AND e.run_id <> p.run_id
    ) THEN RAISE(ABORT, 'action plan update would break evidence links') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_dependencies AS ad
        JOIN actions AS d ON d.id = ad.depends_on_action_id
        WHERE ad.action_id = OLD.id AND d.plan_id <> NEW.plan_id
    ) OR EXISTS (
        SELECT 1
        FROM action_dependencies AS ad
        JOIN actions AS dependent ON dependent.id = ad.action_id
        WHERE ad.depends_on_action_id = OLD.id AND dependent.plan_id <> NEW.plan_id
    ) THEN RAISE(ABORT, 'action plan update would break dependency links') END;
END;

CREATE TRIGGER trg_plan_aggregate_evidence_insert
BEFORE INSERT ON evidence
BEGIN
    SELECT CASE WHEN NEW.resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM resource_refs AS rr
        WHERE rr.id = NEW.resource_ref_id AND rr.run_id = NEW.run_id
    ) THEN RAISE(ABORT, 'evidence resource_ref must belong to evidence run') END;
    SELECT CASE WHEN NEW.origin_type = 'USER_MESSAGE' AND NOT EXISTS (
        SELECT 1
        FROM runs AS r
        JOIN messages AS m ON m.id = NEW.message_id
        WHERE r.id = NEW.run_id AND m.conversation_id = r.conversation_id
    ) THEN RAISE(ABORT, 'user-message evidence must belong to run conversation') END;
END;

CREATE TRIGGER trg_plan_aggregate_evidence_update
BEFORE UPDATE OF run_id, origin_type, resource_ref_id, message_id ON evidence
BEGIN
    SELECT CASE WHEN NEW.resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM resource_refs AS rr
        WHERE rr.id = NEW.resource_ref_id AND rr.run_id = NEW.run_id
    ) THEN RAISE(ABORT, 'evidence resource_ref must belong to evidence run') END;
    SELECT CASE WHEN NEW.origin_type = 'USER_MESSAGE' AND NOT EXISTS (
        SELECT 1
        FROM runs AS r
        JOIN messages AS m ON m.id = NEW.message_id
        WHERE r.id = NEW.run_id AND m.conversation_id = r.conversation_id
    ) THEN RAISE(ABORT, 'user-message evidence must belong to run conversation') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_evidence AS ae
        JOIN actions AS a ON a.id = ae.action_id
        JOIN plans AS p ON p.id = a.plan_id
        WHERE ae.evidence_id = OLD.id AND p.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'evidence run update would break action links') END;
END;

CREATE TRIGGER trg_plan_aggregate_plan_run_update
BEFORE UPDATE OF run_id ON plans
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN resource_refs AS rr ON rr.id = a.target_resource_ref_id
        WHERE a.plan_id = OLD.id AND rr.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN action_evidence AS ae ON ae.action_id = a.id
        JOIN evidence AS e ON e.id = ae.evidence_id
        WHERE a.plan_id = OLD.id AND e.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'plan run update would break aggregate links') END;
END;

CREATE TRIGGER trg_plan_aggregate_resource_run_update
BEFORE UPDATE OF run_id ON resource_refs
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        WHERE a.target_resource_ref_id = OLD.id AND p.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1 FROM evidence AS e
        WHERE e.resource_ref_id = OLD.id AND e.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1
        FROM execution_attempts AS ea
        JOIN approvals AS ap ON ap.id = ea.approval_id
        JOIN actions AS a ON a.id = ap.action_id
        JOIN plans AS p ON p.id = a.plan_id
        WHERE ea.result_resource_ref_id = OLD.id AND p.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'resource_ref run update would break aggregate links') END;
END;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
