-- Pūreretā Ahutoru schema v1

CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER PRIMARY KEY
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);

CREATE TABLE IF NOT EXISTS storage_locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  description TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS empty_spool_weights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brand TEXT NOT NULL,
  model TEXT,
  weight_g REAL NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS spools (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brand TEXT NOT NULL,
  material TEXT NOT NULL,
  color_name TEXT,
  color_hex TEXT,
  purchase_price REAL,
  purchase_date TEXT,
  supplier TEXT,
  batch_number TEXT,
  rating INTEGER CHECK (rating IS NULL OR (rating >= 0 AND rating <= 5)),
  photo_path TEXT,
  location_id INTEGER REFERENCES storage_locations(id) ON DELETE SET NULL,
  remaining_g REAL,
  initial_weight_g REAL DEFAULT 1000,
  empty_spool_weight_g REAL,
  nfc_tag_id TEXT,
  qr_code_id TEXT UNIQUE,
  bambu_tag_uid TEXT UNIQUE,
  bambu_tray_info_idx TEXT,
  notes TEXT,
  low_stock_threshold_g REAL DEFAULT 100,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_spools_material ON spools(material);
CREATE INDEX IF NOT EXISTS idx_spools_location ON spools(location_id);
CREATE INDEX IF NOT EXISTS idx_spools_bambu_tag ON spools(bambu_tag_uid);

CREATE TABLE IF NOT EXISTS drying_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  spool_id INTEGER NOT NULL REFERENCES spools(id) ON DELETE CASCADE,
  dried_at TEXT NOT NULL,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_drying_logs_spool ON drying_logs(spool_id);

CREATE TABLE IF NOT EXISTS printers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  model TEXT NOT NULL DEFAULT 'P1S',
  serial TEXT,
  lan_ip TEXT,
  cloud_device_id TEXT,
  is_default INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ams_slot_mappings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  printer_id INTEGER NOT NULL REFERENCES printers(id) ON DELETE CASCADE,
  slot INTEGER NOT NULL CHECK (slot >= 1 AND slot <= 4),
  spool_id INTEGER REFERENCES spools(id) ON DELETE SET NULL,
  mqtt_tray_type TEXT,
  mqtt_tray_color TEXT,
  mqtt_tray_info_idx TEXT,
  mqtt_tag_uid TEXT,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(printer_id, slot)
);

CREATE TABLE IF NOT EXISTS print_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT,
  started_at TEXT,
  ended_at TEXT,
  duration_s INTEGER,
  status TEXT NOT NULL DEFAULT 'completed',
  source TEXT NOT NULL DEFAULT 'manual',
  printer_id INTEGER REFERENCES printers(id) ON DELETE SET NULL,
  bambu_task_id TEXT UNIQUE,
  gcode_file TEXT,
  needs_review INTEGER NOT NULL DEFAULT 0,
  review_note TEXT,
  completion_percent REAL DEFAULT 100,
  total_used_g REAL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_print_jobs_review ON print_jobs(needs_review);
CREATE INDEX IF NOT EXISTS idx_print_jobs_started ON print_jobs(started_at);

CREATE TABLE IF NOT EXISTS print_usages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  print_job_id INTEGER NOT NULL REFERENCES print_jobs(id) ON DELETE CASCADE,
  ams_slot INTEGER,
  spool_id INTEGER REFERENCES spools(id) ON DELETE SET NULL,
  material TEXT,
  color TEXT,
  used_g REAL NOT NULL DEFAULT 0,
  used_m REAL,
  resolved INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_print_usages_job ON print_usages(print_job_id);

CREATE TABLE IF NOT EXISTS sync_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

INSERT OR IGNORE INTO app_settings (key, value) VALUES
  ('default_low_stock_threshold_g', '100'),
  ('material_low_stock_thresholds', '{}');

INSERT OR IGNORE INTO printers (id, name, model, is_default) VALUES (1, 'P1S', 'P1S', 1);

INSERT OR IGNORE INTO ams_slot_mappings (printer_id, slot) VALUES
  (1, 1), (1, 2), (1, 3), (1, 4);
