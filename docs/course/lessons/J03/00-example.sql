EXPLAIN (ANALYZE, BUFFERS)
SELECT execution_id, dispatch_state, created_at
FROM task_submission
WHERE owner_id = 'user-1' AND dispatch_state = 'pending'
ORDER BY created_at DESC
LIMIT 20;

CREATE INDEX idx_task_owner_dispatch_state_created
ON task_submission (owner_id, dispatch_state, created_at DESC);
