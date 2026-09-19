# 历史记录：v4制作时的报告，不是v4.2实测

# v4实际验证记录

日期：2026-09-17。环境：Python 3.13.5；Java版本见下文。**这里是教材制作时的真实执行记录，不是你已经完成课程，也不是完整项目测试。** 机器记录见[results.json](results.json)。

| 对象 | 本次实际动作 | 结果与边界 |
| --- | --- | --- |
| 34课 / 170份核心文档 | 课数、顺序、前置、课时、32周分配、相对链接、Python语法检查 | 通过；795条本地链接、55个Python文件语法检查 |
| 31个标准库概念例子 | 各自作为新进程实际执行 | 31个正常退出；只覆盖示例行为，不证明真实框架/API |
| 2个Java概念例子 | 各自独立编译并运行 | 2个正常退出；不含数据库或Java/Python服务联调 |
| 8类错误练习的参考实现 | 在临时副本替换student.py，运行28项单元测试 | 通过；没有改发给学习者的故意错误版本 |
| 学生错误版本 | 原样执行同一28项测试 | 初始红灯符合练习设计；具体失败/错误见原始日志，不假称全部应通过 |
| 学习工具与公开裁判 | 19项回归：init、pack、lab、review、敏感样式/符号链接、重复保护、原bug/真实修复/越界修改 | 全部通过；裁判内部9个分页测试方法，包含固定种子的公开数据变体 |
| L00最小骨架 | 回归中实际触发首次测试 | NotImplementedError为设计中的待实现项，不是完整应用 |
| 8个真实框架脚本 | AST语法检查、依赖状态检查 | 语法通过；运行blocked，不能用上述标准库测试替代 |
| 真实API / SQL / 持久副作用 / 完整服务 | 本次未接入 | 未验证；按G1/GF/GR/G4逐项完成 |

## 当前检查结论

教材与离线工具本次检查：**通过**。这个结论不包括框架运行受阻的部分，也不包括完整课程应用。静态检查命令：`python tools/check_course.py`；工具回归：`python tools/test_tools.py`。两条命令均不调用付费API。

## 框架依赖为何保持blocked

本次创建隔离环境并尝试安装候选包，又显式指定官方PyPI索引重试；均返回`from versions: none / No matching distribution found`。日志见[v4-pip.log](v4-pip.log)和[v4-pip-public.log](v4-pip-public.log)。官方发行页可确认候选版本存在，但未能在本机取得包，因此不能写成“框架已运行”。候选依赖清单不当作实测锁文件；F05还必须真正跨进程执行，不能用内存状态代替。

## 系统边界

公开验收器只运行自有受控教学代码，不是恶意代码沙箱；`-I`、超时和文件范围检查不能代替OS级隔离。API密钥检测只覆盖少量模式，上传前仍需人工检查。公开练习可能被背答案，通过它不等于通过未见毕业任务。

## 浏览器验证

通过Chromium实际执行了170个课程页签、34份AI指令内容映射、答案提示、搜索、复制降级流程及1440/390像素宽度布局检查，未出现JavaScript错误。完整记录见[browser.json](browser.json)。

环境策略阻止直接导航file://，因此使用Playwright把同一自包含HTML载入浏览器内存进行检查；**未把它宣称为本机双击file://的端到端验证**。剪贴板写入受浏览器限制时，已检查“选中完整文本手动复制”的降级路径，不冒称系统剪贴板写读都成功。桌面/手机宽度截图已人工查看，没有页面横向溢出；不代表已测所有操作系统与浏览器。

## 当前Java环境

```text
openjdk version "21.0.11" 2026-04-21
OpenJDK Runtime Environment (build 21.0.11+10-1-deb13u2-Debian)
OpenJDK 64-Bit Server VM (build 21.0.11+10-1-deb13u2-Debian, mixed mode, sharing)
```

## 28项参考练习的实际输出

```text
test_delta (test_bug_lab.TestF04.test_delta) ... ok
test_merge_once (test_bug_lab.TestF04.test_merge_once) ... ok
test_blank_does_not_call (test_bug_lab.TestL00.test_blank_does_not_call) ... ok
test_non_string_response_is_invalid (test_bug_lab.TestL00.test_non_string_response_is_invalid) ... ok
test_success_uses_clean_input (test_bug_lab.TestL00.test_success_uses_clean_input) ... ok
test_timeout_is_separate (test_bug_lab.TestL00.test_timeout_is_separate) ... ok
test_child_is_allowed (test_bug_lab.TestL02.test_child_is_allowed) ... ok
test_parent_escape_is_denied (test_bug_lab.TestL02.test_parent_escape_is_denied) ... ok
test_sibling_is_denied (test_bug_lab.TestL02.test_sibling_is_denied) ... ok
test_changed_base (test_bug_lab.TestL07.test_changed_base) ... ok
test_missing_base (test_bug_lab.TestL07.test_missing_base) ... ok
test_same_base (test_bug_lab.TestL07.test_same_base) ... ok
test_keys_do_not_collide (test_bug_lab.TestL10.test_keys_do_not_collide) ... ok
test_same_scope_reuses_key (test_bug_lab.TestL10.test_same_scope_reuses_key) ... ok
test_tenants_do_not_collide (test_bug_lab.TestL10.test_tenants_do_not_collide) ... ok
test_claim_is_not_the_grader (test_bug_lab.TestL12.test_claim_is_not_the_grader) ... ok
test_current_pass (test_bug_lab.TestL12.test_current_pass) ... ok
test_old_report (test_bug_lab.TestL12.test_old_report) ... ok
test_wrong_scope (test_bug_lab.TestL12.test_wrong_scope) ... ok
test_zero_tests (test_bug_lab.TestL12.test_zero_tests) ... ok
test_denominator_is_all_relevant (test_bug_lab.TestR01.test_denominator_is_all_relevant) ... ok
test_duplicate_hit_counts_once (test_bug_lab.TestR01.test_duplicate_hit_counts_once) ... ok
test_miss (test_bug_lab.TestR01.test_miss) ... ok
test_no_relevance_separate (test_bug_lab.TestR01.test_no_relevance_separate) ... ok
test_duplicate_does_not_vote_twice (test_bug_lab.TestR02.test_duplicate_does_not_vote_twice) ... ok
test_empty_backend (test_bug_lab.TestR02.test_empty_backend) ... ok
test_negative_constant (test_bug_lab.TestR02.test_negative_constant) ... ok
test_stable_tie (test_bug_lab.TestR02.test_stable_tie) ... ok

----------------------------------------------------------------------
Ran 28 tests in 0.002s

OK
```

## 19项工具回归的实际输出

```text
test_doctor_no_api (__main__.TestCourseTools.test_doctor_no_api) ... ok
test_init_existing_refused (__main__.TestCourseTools.test_init_existing_refused) ... ok
test_init_inside_course_refused (__main__.TestCourseTools.test_init_inside_course_refused) ... ok
test_init_new_project (__main__.TestCourseTools.test_init_new_project) ... ok
test_lab_copy_no_answer (__main__.TestCourseTools.test_lab_copy_no_answer) ... ok
test_pack_detects_obvious_key (__main__.TestCourseTools.test_pack_detects_obvious_key) ... ok
test_pack_does_not_include_environment (__main__.TestCourseTools.test_pack_does_not_include_environment) ... ok
test_pack_excludes_symlink (__main__.TestCourseTools.test_pack_excludes_symlink) ... ok
test_pack_never_overwrites (__main__.TestCourseTools.test_pack_never_overwrites) ... ok
test_pack_one_instruction_and_hashes (__main__.TestCourseTools.test_pack_one_instruction_and_hashes) ... ok
test_review_dates (__main__.TestCourseTools.test_review_dates) ... ok
test_review_invalid_date (__main__.TestCourseTools.test_review_invalid_date) ... ok
test_starter_expected_red (__main__.TestCourseTools.test_starter_expected_red) ... ok
test_unknown_lesson_refused (__main__.TestCourseTools.test_unknown_lesson_refused) ... ok
test_extra_file_rejected (__main__.TestFixtureGrader.test_extra_file_rejected) ... ok
test_missing_workspace_blocked (__main__.TestFixtureGrader.test_missing_workspace_blocked) ... ok
test_original_bug_is_rejected (__main__.TestFixtureGrader.test_original_bug_is_rejected) ... ok
test_real_fix_is_accepted (__main__.TestFixtureGrader.test_real_fix_is_accepted) ... ok
test_unrelated_file_change_rejected (__main__.TestFixtureGrader.test_unrelated_file_change_rejected) ... ok

----------------------------------------------------------------------
Ran 19 tests in 14.724s

OK
```

## 概念例子的实际输出

### lessons/F01/00-example.py

退出码：0。

```text
{'role': 'user', 'content': 'explain pagination'}
fixture: explain pagination
type_error: rejected before model
```

### lessons/F02/00-example.py

退出码：0。

```text
{"content": "def page(items): return items", "tool_call_id": "call-1"}
unauthorized
```

### lessons/F03/00-example.py

退出码：0。

```text
schema_error
missing_evidence
verified_fixture
```

### lessons/F04/00-example.py

退出码：0。

```text
delta: {'budget': 1, 'evidence': ['read:v1', 'test:failed']}
full-history mistake: {'budget': 2, 'evidence': ['read:v1', 'read:v1', 'test:failed']}
```

### lessons/F05/00-example.py

退出码：0。

```text
created
reused
idempotency_conflict
effect_count: 1
```

### lessons/F06/00-example.py

退出码：0。

```text
approved
stale_approval
cancelled
unauthorized
```

### lessons/L00/00-example.py

退出码：0。

```text
invalid_input
model_timeout
invalid_response
succeeded
```

### lessons/L01/00-example.py

退出码：0。

```text
{'text': 'hello', 'input_tokens': None, 'output_tokens': None}
{'text': 'hello', 'input_tokens': 12, 'output_tokens': 3}
```

### lessons/L02/00-example.py

退出码：0。

```text
True
True
False
```

### lessons/L03/00-example.py

退出码：0。

```text
{'call_id': 'c1', 'ok': True, 'data': 6}
{'call_id': 'c2', 'ok': False, 'code': 'invalid_args'}
```

### lessons/L04/00-example.py

退出码：0。

```text
done 2
['tool', 'tool_result', 'final']
```

### lessons/L05/00-example.py

退出码：0。

```text
pagination.py
{'ok': True, 'matches': []}
```

### lessons/L06/00-example.py

退出码：0。

```text
workflow
ask_metric
agent
```

### lessons/L07/00-example.py

退出码：0。

```text
False
conflict
```

### lessons/L08/00-example.py

退出码：0。

```text
b'abcdefghij'
True
```

### lessons/L09/00-example.py

退出码：0。

```text
no_tests
collection_error
passed
```

### lessons/L10/00-example.py

退出码：0。

```text
applied
replayed
conflict
```

### lessons/L11/00-example.py

退出码：0。

```text
continue
continue
stop
```

### lessons/L12/00-example.py

退出码：0。

```text
True
False
False
False
```

### lessons/L13/00-example.py

退出码：0。

```text
symbol
text
unavailable
```

### lessons/L14/00-example.py

退出码：0。

```text
{'items': ['a', 'b'], 'truncated': True, 'next_offset': 2}
{'items': [], 'truncated': False, 'next_offset': None}
```

### lessons/L15/00-example.py

退出码：0。

```text
['search_text', 'read_file']
```

### lessons/L16/00-example.py

退出码：0。

```text
['keep public signature']
pagination.py
```

### lessons/L17/00-example.py

退出码：0。

```text
large 0.08 2
small 0.1 5
```

### lessons/L18/00-example.py

退出码：0。

```text
old {'text': (3, 4), 'symbol': (1, 2)}
new {'text': (2, 4), 'symbol': (2, 2)}
```

### lessons/L19/00-example.py

退出码：0。

```text
True
False
```

### lessons/L20/00-example.py

退出码：0。

```text
stop_before_next_step
reconcile
skip_duplicate_write
```

### lessons/L21/00-example.py

退出码：0。

```text
exec-7
forbidden
```

### lessons/L22/00-example.py

退出码：0。

```text
tool_routing supported
distributed_ha gap
```

### lessons/R01/00-example.py

退出码：0。

```text
[('d1', 1.3938), ('d3', 0.5119)]
no_answer: []
```

### lessons/R02/00-example.py

退出码：0。

```text
[('d2', 0.032522), ('d1', 0.016393), ('d3', 0.016129)]
dedupe_and_acl: passed
semantic_rankings: synthetic_fixture_not_model_measurement
```

### lessons/J01/Demo.java

状态：passed_exit_only。

```text
null
bodyA
bodyA
bodyA
```

### lessons/J02/Demo.java

状态：passed_exit_only。

```text
rejected=1
```

