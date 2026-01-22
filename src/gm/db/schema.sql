-- Play Log Schema with Scenario > Act > Sequence > Action hierarchy

CREATE TABLE IF NOT EXISTS play_logs (
    id SERIAL PRIMARY KEY,

    -- Hierarchy & Identity
    turn_id VARCHAR(100) NOT NULL UNIQUE, -- session_id:seq
    session_id VARCHAR(50) NOT NULL,      -- Represents the Scenario Playthrough

    -- Context
    act_id VARCHAR(50),                   -- Current Act Context

    -- Sequence Detail
    sequence_id VARCHAR(50),              -- Unique ID of the sequence instance
    sequence_type VARCHAR(50),            -- e.g., 'COMBAT', 'EXPLORATION', 'DIALOGUE'
    sequence_seq INT,                     -- N-th sequence in the current Act

    turn_seq INT NOT NULL,                -- Sequence number of this Action (Turn)

    -- Action Subject
    active_entity_id VARCHAR(50) NOT NULL, -- 'player' or NPC ID

    -- Action Content
    user_input TEXT NOT NULL,             -- The action description/command
    final_output TEXT,                    -- The resulting narrative

    -- State Tracking
    state_diff JSONB,                     -- Changes applied in this turn
    world_snapshot JSONB,                 -- List of active instances in the current Sequence
    commit_id VARCHAR(50),                -- Commit ID from State Manager

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    meta_info JSONB                       -- Extra metadata (model used, latency, etc.)
);

CREATE INDEX IF NOT EXISTS idx_play_logs_session_id ON play_logs(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_play_logs_session_turn_seq ON play_logs(session_id, turn_seq);
CREATE INDEX IF NOT EXISTS idx_play_logs_hierarchy ON play_logs(session_id, act_id, sequence_id);
