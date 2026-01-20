CREATE TABLE IF NOT EXISTS play_logs (
    id SERIAL PRIMARY KEY,
    turn_id VARCHAR(100) NOT NULL UNIQUE, -- session_id + seq
    session_id VARCHAR(50) NOT NULL,
    turn_seq INT NOT NULL, -- 세션 내 순번
    user_input TEXT NOT NULL,
    final_output TEXT,
    state_diff JSONB,
    commit_id VARCHAR(50), -- State Manager가 발급한 commit_id
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    meta_info JSONB -- llm model, rule version etc
);

CREATE INDEX IF NOT EXISTS idx_play_logs_session_id ON play_logs(session_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_play_logs_session_turn_seq ON play_logs(session_id, turn_seq);
