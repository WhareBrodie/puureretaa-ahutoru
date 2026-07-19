-- Bambu tag_uid is shared across many filament colours; tray_info_idx is the product key.

DROP INDEX IF EXISTS idx_bambu_filament_rfid_tag;
CREATE INDEX IF NOT EXISTS idx_bambu_filament_rfid_tag ON bambu_filament_rfid(tag_uid)
  WHERE tag_uid IS NOT NULL AND tag_uid != '';

INSERT INTO schema_version (version) VALUES (6);
