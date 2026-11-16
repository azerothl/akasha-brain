CREATE TABLE work_orders (
    order_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('open', 'done', 'on_hold')),
    priority_score INTEGER
);
