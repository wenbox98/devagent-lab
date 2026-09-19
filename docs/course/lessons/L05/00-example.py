hits = [
    {"path": "reporting.py", "symbol": "page", "purpose": "format report"},
    {"path": "pagination.py", "symbol": "page", "purpose": "slice items"},
]
candidates = [h for h in hits if h["purpose"] == "slice items"]
print(candidates[0]["path"])
print({"ok": True, "matches": []})
