def choose_action(task):
    if task.get("operation") == "run_named_test" and task.get("test"):
        return "workflow"
    if task.get("operation") == "optimize" and not task.get("metric"):
        return "ask_metric"
    return "agent"

print(choose_action({"operation": "run_named_test", "test": "test_page"}))
print(choose_action({"operation": "optimize"}))
print(choose_action({"operation": "fix", "bug": "wrong first page"}))
