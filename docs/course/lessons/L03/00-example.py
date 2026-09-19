registry = {"double": lambda x: x * 2}

def execute(call):
    if call["name"] not in registry:
        return {"call_id": call["id"], "ok": False, "code": "unknown_tool"}
    value = call["arguments"].get("x")
    if type(value) is not int:
        return {"call_id": call["id"], "ok": False, "code": "invalid_args"}
    return {"call_id": call["id"], "ok": True,
            "data": registry[call["name"]](value)}

print(execute({"id": "c1", "name": "double", "arguments": {"x": 3}}))
print(execute({"id": "c2", "name": "double", "arguments": {"x": True}}))
