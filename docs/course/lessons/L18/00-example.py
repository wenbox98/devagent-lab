runs = {
    "old": {"text": [1, 1, 1, 0], "symbol": [1, 0]},
    "new": {"text": [1, 1, 0, 0], "symbol": [1, 1]},
}
for version, groups in runs.items():
    print(version, {g: (sum(v), len(v)) for g, v in groups.items()})
