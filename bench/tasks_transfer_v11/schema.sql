CREATE TABLE support_tickets (
    ticket_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'done', 'cancelled')),
    archived_at TEXT,
    closing_code TEXT
);
