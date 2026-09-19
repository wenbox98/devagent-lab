def handle(task, client):
    task = task.strip()
    if not task:
        return "invalid_input"
    try:
        text = client(task)
    except TimeoutError:
        return "model_timeout"
    if not text.strip():
        return "invalid_response"
    return "succeeded"

def timeout_client(task):
    raise TimeoutError("simulated")

print(handle("  ", lambda task: "ok"))
print(handle("fix", timeout_client))
print(handle("fix", lambda task: ""))
print(handle("fix", lambda task: "ok"))
