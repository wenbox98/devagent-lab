def route(query_kind, index_ready, index_fresh, allowed):
    eligible = [name for name in ("text", "symbol") if name in allowed]
    if not index_ready or not index_fresh:
        eligible = [name for name in eligible if name != "symbol"]
    preferred = "symbol" if query_kind == "symbol" else "text"
    if preferred in eligible:
        return preferred
    return eligible[0] if eligible else "unavailable"

print(route("symbol", True, True, {"text", "symbol"}))
print(route("symbol", True, False, {"text", "symbol"}))
print(route("symbol", True, True, set()))
