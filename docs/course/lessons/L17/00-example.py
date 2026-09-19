strategies = {"large": [0.04, 0.04], "small": [0.02] * 5}
for name, calls in strategies.items():
    print(name, round(sum(calls), 2), len(calls))
