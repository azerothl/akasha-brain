CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('open', 'closed', 'cancelled')),
    priority INTEGER NOT NULL,
    assignee TEXT,
    hold_until INTEGER,
    due_day INTEGER
);
