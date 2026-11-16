CREATE TABLE interventions (
    ticket_id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL,
    queue TEXT NOT NULL CHECK (queue IN ('normal', 'deferred', 'cancelled')),
    confirmed_at TEXT
);
