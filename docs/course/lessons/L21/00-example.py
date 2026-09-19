submission = {"owner": "alice", "execution_id": "exec-7"}
def authorize(current_user):
    if current_user != submission["owner"]:
        return "forbidden"
    return submission["execution_id"]

print(authorize("alice"))
print(authorize("bob"))
