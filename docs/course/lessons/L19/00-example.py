allowed = {
    "queued": {"running", "cancelled"},
    "running": {"succeeded", "failed", "waiting_input", "cancelled"},
    "waiting_input": {"queued", "cancelled"},
}
def can_move(old, new):
    return new in allowed.get(old, set())

print(can_move("queued", "running"))
print(can_move("succeeded", "running"))
