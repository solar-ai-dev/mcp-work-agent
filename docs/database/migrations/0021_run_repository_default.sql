-- Preserve the user-selected Settings default at Run creation, not at resume.
BEGIN IMMEDIATE;
ALTER TABLE runs ADD COLUMN default_github_repository_json TEXT
    CHECK (default_github_repository_json IS NULL OR (
        json_valid(default_github_repository_json)
        AND length(default_github_repository_json) <= 1024
    ));
COMMIT;
PRAGMA foreign_key_check;
