CREATE TABLE state_catalog (
    code TEXT PRIMARY KEY NOT NULL,
    label TEXT NOT NULL,
    is_terminal INTEGER NOT NULL CHECK (is_terminal IN (0, 1))
);

CREATE TABLE queue_items (
    item_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    state_code TEXT NOT NULL REFERENCES state_catalog (code)
);
