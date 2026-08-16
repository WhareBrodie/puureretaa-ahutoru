-- Store AMS tray mapping captured from MQTT when a print starts.
-- Cloud task history often omits ams_mapping; slicer filament ids are NOT AMS slots.

CREATE TABLE IF NOT EXISTS bambu_print_ams_mapping (
  task_id TEXT PRIMARY KEY,
  ams_mapping TEXT NOT NULL,
  gcode_file TEXT,
  subtask_name TEXT,
  captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bambu_active_print_mapping (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  task_id TEXT,
  ams_mapping TEXT NOT NULL,
  gcode_file TEXT,
  subtask_name TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO schema_version (version) VALUES (9);
