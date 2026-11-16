CREATE TABLE work_items (
    item_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    closed_on TEXT,
    deferred_until TEXT
);

CREATE TABLE prerequisites (
    item_id INTEGER NOT NULL REFERENCES work_items (item_id),
    required_item_id INTEGER NOT NULL REFERENCES work_items (item_id),
    PRIMARY KEY (item_id, required_item_id)
);
