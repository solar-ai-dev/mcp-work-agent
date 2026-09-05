-- Register the existing GitHub connector resource identity for generic ResourceRef persistence.
BEGIN IMMEDIATE;

INSERT OR IGNORE INTO registered_connectors (connector_id)
VALUES ('github');

INSERT OR IGNORE INTO registered_connector_resource_types (connector_id, resource_type)
VALUES ('github', 'github_issue');

COMMIT;

PRAGMA foreign_key_check;
