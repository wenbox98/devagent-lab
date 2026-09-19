script = [
    {"kind": "tool", "name": "read", "id": "c1"},
    {"kind": "final", "text": "found"},
]
history = []
for step in range(3):
    reply = script[step]
    history.append(reply)
    if reply["kind"] == "final":
        print("done", step + 1)
        break
    history.append({"kind": "tool_result", "id": reply["id"], "data": "code"})
print([x["kind"] for x in history])
