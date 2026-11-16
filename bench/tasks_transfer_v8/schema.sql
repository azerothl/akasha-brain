CREATE TABLE task_log (
    task_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL
);

CREATE TABLE close_receipt (
    receipt_id INTEGER PRIMARY KEY,
    task_id INTEGER NOT NULL REFERENCES task_log (task_id),
    accepted INTEGER NOT NULL CHECK (accepted IN (0, 1))
);
