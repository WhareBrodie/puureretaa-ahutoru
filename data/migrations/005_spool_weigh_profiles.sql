-- Last scale weigh-in and link spools to reusable empty-spool profiles.

ALTER TABLE spools ADD COLUMN last_weighed_at TEXT;
ALTER TABLE spools ADD COLUMN empty_spool_weight_id INTEGER REFERENCES empty_spool_weights(id) ON DELETE SET NULL;

INSERT INTO empty_spool_weights (brand, model, weight_g, notes)
SELECT 'Bambu Lab', 'Plastic spool', 238, 'Refill / plastic spool'
WHERE NOT EXISTS (
  SELECT 1 FROM empty_spool_weights
  WHERE brand = 'Bambu Lab' AND COALESCE(model, '') = 'Plastic spool'
);

INSERT INTO schema_version (version) VALUES (5);
