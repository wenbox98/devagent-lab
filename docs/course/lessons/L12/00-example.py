def grade(target_passed, regression_passed, tests_run, scope_ok):
    return (target_passed and regression_passed
            and tests_run > 0 and scope_ok)

print(grade(True, True, 3, True))
print(grade(True, False, 3, True))
print(grade(True, True, 0, True))
print(grade(True, True, 3, False))
