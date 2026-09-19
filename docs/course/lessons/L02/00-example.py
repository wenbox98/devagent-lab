from pathlib import PurePosixPath

root = PurePosixPath("/work/repo")
good = PurePosixPath("/work/repo/src/main.py")
bad = PurePosixPath("/work/repo2/main.py")
print(str(bad).startswith(str(root)))
print(good.is_relative_to(root))
print(bad.is_relative_to(root))
