def next_action(cancel_requested, operation_state):
    if cancel_requested:
        return "stop_before_next_step"
    if operation_state == "unknown":
        return "reconcile"
    if operation_state == "applied":
        return "skip_duplicate_write"
    return "execute"

for pair in [(True, "pending"), (False, "unknown"), (False, "applied")]:
    print(next_action(*pair))
