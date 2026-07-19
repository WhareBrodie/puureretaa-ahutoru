-- Permanently ignore Bambu cloud task IDs so cleared history cannot be re-imported.

CREATE TABLE IF NOT EXISTS bambu_ignored_tasks (
  task_id TEXT PRIMARY KEY,
  reason TEXT,
  ignored_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO schema_version (version) VALUES (4);
