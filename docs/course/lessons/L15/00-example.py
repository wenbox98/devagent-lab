catalog = {
    "read_file": {"read", "code"},
    "search_text": {"search", "code"},
    "run_tests": {"test", "execute"},
}
query_tags = {"search", "code"}
ranked = sorted(catalog, key=lambda n: len(catalog[n] & query_tags), reverse=True)
print(ranked[:2])
