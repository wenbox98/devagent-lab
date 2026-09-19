skills = {
    "tool_routing": {"evidence": "report-L13", "independent": True},
    "distributed_ha": {"evidence": None, "independent": False},
}
for name, item in skills.items():
    status = "supported" if item["evidence"] and item["independent"] else "gap"
    print(name, status)
