-- Mid-print AMS spool swaps: detect runout/replacement, suggest split in review.

CREATE TABLE IF NOT EXISTS bambu_print_slot_swaps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT NOT NULL,
  ams_slot INTEGER NOT NULL,
  old_spool_id INTEGER REFERENCES spools(id) ON DELETE SET NULL,
  new_spool_id INTEGER REFERENCES spools(id) ON DELETE SET NULL,
  old_remaining_g REAL,
  mc_percent_at_detect REAL,
  source TEXT NOT NULL,
  detected_at TEXT NOT NULL DEFAULT (datetime('now')),
  remapped_at TEXT,
  consumed_at TEXT,
  UNIQUE (task_id, ams_slot)
);

CREATE INDEX IF NOT EXISTS idx_bambu_print_slot_swaps_open
  ON bambu_print_slot_swaps(task_id) WHERE consumed_at IS NULL;

ALTER TABLE print_usages ADD COLUMN split_group TEXT;
ALTER TABLE print_usages ADD COLUMN split_role TEXT;

INSERT INTO schema_version (version) VALUES (11);
