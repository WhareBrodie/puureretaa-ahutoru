-- Bambu RFID identifies filament product (e.g. PLA Basic Black), not individual spools.

CREATE TABLE IF NOT EXISTS bambu_filament_rfid (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag_uid TEXT,
  tray_info_idx TEXT,
  brand TEXT NOT NULL,
  material TEXT NOT NULL,
  color_name TEXT,
  color_hex TEXT,
  learned_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bambu_filament_rfid_tag ON bambu_filament_rfid(tag_uid)
  WHERE tag_uid IS NOT NULL AND tag_uid != '';
CREATE UNIQUE INDEX IF NOT EXISTS idx_bambu_filament_rfid_tray ON bambu_filament_rfid(tray_info_idx)
  WHERE tray_info_idx IS NOT NULL AND tray_info_idx != '';

INSERT INTO schema_version (version) VALUES (3);
