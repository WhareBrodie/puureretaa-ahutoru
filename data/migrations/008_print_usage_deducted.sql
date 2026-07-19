ALTER TABLE print_usages ADD COLUMN filament_deducted INTEGER NOT NULL DEFAULT 0;

INSERT INTO schema_version (version) VALUES (8);
