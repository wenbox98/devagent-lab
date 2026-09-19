records = {}
def submit(op_id, payload):
    if op_id in records:
        if records[op_id] != payload:
            return "conflict"
        return "replayed"
    records[op_id] = payload
    return "applied"

print(submit("op-1", "patch-A"))
print(submit("op-1", "patch-A"))
print(submit("op-1", "patch-B"))
