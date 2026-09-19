def classify(exit_code, tests_run, import_error=False, timed_out=False):
    if timed_out:
        return "timeout"
    if import_error:
        return "collection_error"
    if tests_run == 0:
        return "no_tests"
    return "passed" if exit_code == 0 else "assertion_failed"

print(classify(0, 0))
print(classify(1, 0, import_error=True))
print(classify(0, 3))
