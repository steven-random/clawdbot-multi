-- ClawdBot DB Schema
-- Tracks all agent tasks for audit/history

CREATE TABLE IF NOT EXISTS tasks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id     TEXT NOT NULL UNIQUE,
    agent_id    TEXT NOT NULL,
    input_text  TEXT,
    result      TEXT,
    status      TEXT DEFAULT 'pending',
    slack_user  TEXT,
    slack_channel TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);

-- Example tables for the Data Agent to query
CREATE TABLE IF NOT EXISTS sample_metrics (
    id          SERIAL PRIMARY KEY,
    metric_name TEXT,
    value       NUMERIC,
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO sample_metrics (metric_name, value)
VALUES
    ('requests_today', 42),
    ('errors_today', 2),
    ('avg_response_ms', 312)
ON CONFLICT DO NOTHING;
