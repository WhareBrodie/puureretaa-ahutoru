-- One printable label file per filament type (brand + material + colour).

CREATE TABLE IF NOT EXISTS filament_labels (
  id INTEGER PRIMARY KEY,
  brand TEXT NOT NULL,
  material TEXT NOT NULL,
  color_name TEXT NOT NULL DEFAULT '',
  file_path TEXT NOT NULL,
  original_filename TEXT,
  uploaded_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (brand, material, color_name)
);

INSERT INTO schema_version (version) VALUES (10);
