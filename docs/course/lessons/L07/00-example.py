import hashlib

def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()

read_version = digest("start = page_no * size")
current = "start = (page_no - 1) * size"
print(digest(current) == read_version)
print("conflict" if digest(current) != read_version else "can_write")
