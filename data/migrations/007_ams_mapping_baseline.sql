-- Snapshot AMS tray identity when a slot is mapped, so swap detection compares
-- live MQTT to the mapped baseline — not spool inventory strings (PLA vs PLA-MATTE).

ALTER TABLE ams_slot_mappings ADD COLUMN baseline_tray_info_idx TEXT;
ALTER TABLE ams_slot_mappings ADD COLUMN baseline_tray_type TEXT;
ALTER TABLE ams_slot_mappings ADD COLUMN baseline_tray_color TEXT;

UPDATE ams_slot_mappings
SET baseline_tray_info_idx = mqtt_tray_info_idx,
    baseline_tray_type = mqtt_tray_type,
    baseline_tray_color = mqtt_tray_color
WHERE spool_id IS NOT NULL;

INSERT INTO schema_version (version) VALUES (7);
