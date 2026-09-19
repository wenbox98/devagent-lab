# 独立排错练习｜八类错误，不是第二个项目

在学习项目根目录执行：

```bash
python docs/course/tools/course.py lab --project .
python -m unittest discover -s .local/workshops/bug_lab -v
```

第一次失败是预设练习，不是安装损坏。修改对象是学习项目`.local/workshops/bug_lab/student.py`；只读测试是`.local/workshops/bug_lab/test_bug_lab.py`，不要修改它。每学到对应课再做对应Test类，不要求L00时修复全部错误。可用unittest指定单类，先cd进入.local/workshops/bug_lab，再执行`python -m unittest test_bug_lab.TestL00 -v`。

| 课 | 要修的函数 | 判定核心 | 变体 |
| --- | --- | --- | --- |
| L00 | handle | 非法输入没有调用、响应类型与超时分层 | 42、全空格、返回None |
| L02 | is_within | 兄弟目录不是子目录 | repo、repo2、../ |
| L07 | base_matches | 当前基线必须等于预期基线 | 两个不同非空hash |
| L10 | operation_key | 租户隔离且重试稳定 | 同键不同租户 |
| L12 | verified | 当前快照、非零测试、范围合法 | 旧报告、0测试、错误自述 |
| F04 | evidence_delta | 追加reducer只接收新证据 | [a]追加b得到[a,b] |
| R01 | recall_at_k | 分母是全部相关文档，去重命中 | 重复命中、无相关文档 |
| R02 | rrf | 单路重复不重复投票，稳定排序 | 相同得分、一路空列表 |

先写预测，运行失败测试，列两个假设，做最小修改，补一个自己的反例。参考实现在教材根目录[workshops/answers/bug_lab_solution.py](answers/bug_lab_solution.py)，先独立尝试再读。公开参考不是隐藏考试；通过这些测试不能证明全套应用已完成，也不能证明生产安全。

## 真正执行代码的公共参考验收

L12开始，在你生成的受控工作区上运行：

```bash
python docs/course/tools/grade_fixture.py --workspace fixtures/tiny_repo
```

原始练习仓库故意有bug，应该失败。修复分页偏移后、其它文件不变，应通过。这个程序实际调用公共参考测试、检查快照及允许文件，不读取Agent自述。验收脚本要放在Agent写权限之外。只运行自己编写/确认的教学代码；它不是恶意代码沙箱。毕业另需未见仓库与未见任务。

## 概念副本不是这个bug_lab副本

`tools/prepare_example.py`创建的`.local/concepts/课号/`用来改每课小例子的输入。`tools/course.py lab`创建的`.local/workshops/bug_lab/`则是八类故意错误题。它们与应用`devagent/`是三套不同对象；各课实验页已指定当前使用哪一套。

## 当前课测试类的精确执行

运行单课测试时先`cd .local/workshops/bug_lab`，再执行表中测试类：

| 课号 | 只读测试类 | 只修改的函数 |
| --- | --- | --- |
| L00 | `test_bug_lab.TestL00` | `student.py::handle` |
| L02 | `test_bug_lab.TestL02` | `student.py::is_within` |
| L07 | `test_bug_lab.TestL07` | `student.py::base_matches` |
| L10 | `test_bug_lab.TestL10` | `student.py::operation_key` |
| L12 | `test_bug_lab.TestL12` | `student.py::verified` |
| F04 | `test_bug_lab.TestF04` | `student.py::evidence_delta` |
| R01 | `test_bug_lab.TestR01` | `student.py::recall_at_k` |
| R02 | `test_bug_lab.TestR02` | `student.py::rrf` |

例如`python -m unittest test_bug_lab.TestF04 -v`。跑完执行`cd ../../..`返回学习项目根目录。初始整套题红灯是预设状态；参考解在临时副本通过，并不表示你的副本已修复。

L00增加了整数42的明确断言：`test_bug_lab.py::TestL00.test_integer_task_is_rejected_before_client`。只改学生副本的`student.py::handle`，不改这条测试来放行错误实现。

### 已有v4错误练习副本，怎样取得本版新测试

不要覆盖`.local/workshops/bug_lab/student.py`，里面可能已有你的答案。先备份个人副本的`.local/workshops/bug_lab/test_bug_lab.py`，再把本版教材只读测试`docs/course/workshops/bug_lab/test_bug_lab.py`复制到该个人测试路径。这样只更新公开题目检查，保留你的实现；新增整数42断言可能变红，这是要补练的差异。已有副本不用再运行`course.py lab`，它会拒绝覆盖。
