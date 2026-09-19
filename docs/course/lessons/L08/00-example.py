limit = 10
saved = bytearray()
truncated = False
for chunk in [b"abcd", b"efgh", b"ijkl"]:
    room = max(0, limit - len(saved))
    saved.extend(chunk[:room])
    if len(chunk) > room:
        truncated = True
print(bytes(saved))
print(truncated)
