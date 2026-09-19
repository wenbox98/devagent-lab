state = {
    "constraints": ["keep public signature"],
    "summary": "Tried two patches; one test still fails",
    "evidence": [{"path": "pagination.py", "hash": "v1"}],
}
new_summary = "Boundary validation remains"
state["summary"] = new_summary
print(state["constraints"])
print(state["evidence"][0]["path"])
