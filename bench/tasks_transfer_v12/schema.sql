CREATE TABLE interventions (
    intervention_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('queued', 'in_progress', 'finished')),
    release_on TEXT,
    is_suspended INTEGER NOT NULL CHECK (is_suspended IN (0, 1))
);
