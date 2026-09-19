def result_page(items, limit):
    return {
        "items": items[:limit],
        "truncated": len(items) > limit,
        "next_offset": limit if len(items) > limit else None,
    }

print(result_page(["a", "b", "c"], 2))
print(result_page([], 2))
