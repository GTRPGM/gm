-- name: get_session_history
-- Fetch all turn history for a session
SELECT
    session_id,
    act_id,
    sequence_id,
    sequence_type,
    sequence_seq,
    turn_seq,
    active_entity_id,
    user_input,
    final_output,
    created_at
FROM play_logs
WHERE session_id = $1
ORDER BY turn_seq ASC;

-- name: fetch_history_limit
-- Fetch recent history with limit
SELECT user_input, final_output
FROM play_logs
WHERE session_id = $1
ORDER BY turn_seq DESC
LIMIT $2;

-- name: get_next_turn_seq
-- Get the next turn sequence number
SELECT COALESCE(MAX(turn_seq), 0) + 1
FROM play_logs
WHERE session_id = $1;

-- name: insert_play_log
-- Insert a new play log entry
INSERT INTO play_logs (
    turn_id,
    session_id,
    turn_seq,
    user_input,
    final_output,
    state_diff,
    commit_id,
    act_id,
    sequence_id,
    sequence_type,
    sequence_seq,
    active_entity_id,
    world_snapshot
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13);
