def normalize(raw):
    return {
        "text": raw.get("answer", ""),
        "input_tokens": raw.get("usage", {}).get("input"),
        "output_tokens": raw.get("usage", {}).get("output"),
    }

print(normalize({"answer": "hello"}))
print(normalize({"answer": "hello",
                 "usage": {"input": 12, "output": 3}}))
