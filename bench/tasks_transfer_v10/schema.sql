CREATE TABLE work_cards (
    card_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    completed INTEGER NOT NULL CHECK (completed IN (0, 1)),
    assignee TEXT
);
