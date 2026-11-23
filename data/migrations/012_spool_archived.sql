-- Manual spool archive: hide from AMS/review/manual dropdowns and inventory
-- unless "Show archived" is on. Zero remaining never auto-archives.

ALTER TABLE spools ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;

INSERT INTO schema_version (version) VALUES (12);
