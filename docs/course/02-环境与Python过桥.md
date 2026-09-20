# 环境与Python过桥：按需要安装，不一次堆满

> 历史参考保留：本页沿用v4.2材料，不要求当前学习者重新从头执行。现行阅读路径见[从这里开始](00-从这里开始.md)，实际代码差距见[当前基线](19-当前代码基线与学习接续.md)，关键技术澄清见[修订审计](24-教材审计与修订取舍.md)。旧版验证/版本声明不能当本轮实测。

## 0. v4环境边界

概念练习和工具使用Python标准库，语法基线3.12。制作时实际执行的版本写在[验证报告](validation/report.md)，不把3.13上通过说成所有3.12/Windows环境已测。Java/SQL/真实API是独立验证项。

先运行 `python tools/course.py doctor`。它检查解释器、Git和框架包信息，不联网、不收集密钥，也不证明依赖兼容。系统没有`python`命令时，Windows可先用`py --version`确认启动器，再在相同解释器中创建虚拟环境。后续命令均在项目根执行。

```bash
python -m venv .venv
```

Windows PowerShell可直接使用 `.venv\Scripts\python.exe`，不用为激活脚本全局降低执行策略；macOS/Linux可用 `.venv/bin/python`。下文`python`均指当前项目解释器。先完成L00，安装框架不是首课前置。

### F01再安装框架

```bash
python -m pip install -r docs/course/requirements-framework.in
python -m pip check
python docs/course/tools/course.py doctor
python docs/course/lessons/F01/framework-example.py
```

`requirements-framework.in`是**候选直接依赖清单，不是已经运行验证过的锁文件**。当前制作环境安装失败，相关日志随验证报告保留。包存在于官方发布页，不代表本环境能安装；安装错误也不自动说明版本不存在。依赖安装、pip check、真实框架例子运行都通过后，才将你的实际`pip freeze`保存在项目证据中；升级用独立分支重测。不要同时加载历史v3的另一个环境清单。

F05需要`langgraph-checkpoint-sqlite`和本地可写数据库文件，使用纯基本类型作为检查点内容；不导入来历不明的检查点。按官方建议限制反序列化类型，数据库不是可随便接收外部上传文件的格式。F05脚本的命令见本课03，首次故意失败和第二进程恢复需分开执行。[SQLite官方说明](https://pypi.org/project/langgraph-checkpoint-sqlite/)

### L01真实模型：必须单独开关

离线FakeClient用于确定性回归；真实模型用你有权限的供应商和模型ID，通过本地环境变量提供凭据。先明确单次预算、请求上限和退出条件，再人工启用`real-once`；默认运行不得扣费。不要把ChatGPT网页订阅、界面模型名和API余额混为一谈。[官方计费区分](https://help.openai.com/en/articles/9039756-billing-settings-in-chatgpt-vs-platform)

### J课和数据库

到J01再准备课程所需JDK、构建工具与数据库。先用小例子理解唯一约束、事务和线程，再执行真实联调。Docker只是可选环境载体，不自动形成安全沙箱；容器隔离、网络与资源策略要在L08/L19中分别验证。下面保留语言过桥讲解，所有排期和验证状态以v4导航和报告为准。

---

[返回开始](00-从这里开始.md) · [课程导航](01-课程导航.md)

## 小桥一：函数与类型标注

```python
def normalize(task: str) -> str:
    return task.strip()

print(normalize("  fix  "))
```

输出fix。def定义函数，冒号开始缩进块；参数后的str和箭头后的str主要是类型提示，不自动执行校验。与Java不同，Python通常不因传错类型在编译期阻止运行，所以外部输入边界仍要检查。
修改练习：传入None会怎样？原因在调用者还是函数契约？不要直接用str(None)掩盖不合法输入。

## 小桥二：字典、列表与切片

```python
items = [10, 20, 30, 40]
page_no, size = 1, 2
start = (page_no - 1) * size
print(items[start:start + size])
result = {"items": items[:2], "next": None}
print(result["items"])
print(result.get("missing", "unknown"))
```

列表切片左闭右开，第一页从下标0开始。字典相当于常见Map，但键不存在时下标访问会抛KeyError，get可以给默认值。默认值不是越多越好：关键字段缺失应报协议错误，不能默认成成功。
修改练习：page\_no=0为何会出现负下标？这说明业务校验要放在哪？

## 小桥三：dataclass是DTO，不是验证器

```python
from dataclasses import dataclass

@dataclass
class Request:
    task: str

request = Request(task="fix")
print(request.task)
```

装饰器@dataclass帮助生成初始化等方法。先会用，不必此时研究装饰器底层。它不会自动拒绝Request(task=None)；若task必须是非空文本，应用要明确验证。
这与Java编译期类型机制不同，不能把类型提示当作运行时Schema。

## 小桥四：异常只在适合的边界转换

```python
def call():
    raise TimeoutError("simulated")

try:
    call()
except TimeoutError:
    print("model_timeout")
```

raise类似throw，except类似catch。只捕获你知道如何处理的错误；不要except Exception后全部返回“网络错误”。定位时保留上下文与原始异常来源，展示给用户的信息要脱敏。
参考 [Python异常教程](https://docs.python.org/3.12/tutorial/errors.html)。

## 小桥五：包、入口与导入错误

python -m devagent表示作为模块运行devagent包。若报No module named devagent，依次检查：

1. 代码目录是否真的存在，AI是否只给了说明没创建文件。
2. 当前目录是不是项目根目录。
3. 调用的是不是预期虚拟环境解释器。
4. 项目若采用src布局，是否按生成说明安装为可编辑包。
   不要见到ModuleNotFoundError就随意pip install一个同名第三方包。

## 小桥六：文件和JSONL

```python
import json
event = {"run_id": "demo", "event": "run_finished", "ok": True}
line = json.dumps(event, ensure_ascii=False)
print(line)
print(json.loads(line)["ok"])
```

Python字典的True序列化到JSON是true；None会变null。JSONL每行保存一个独立对象，适合追加事件。with open(..., "a", encoding="utf-8")追加，"w"会覆盖。
先理解小例子再读完整trace模块，不必先学数据库。

## 到对应课程再准备的环境

| 课程 | 准备什么 | 怎么确认 |
| --- | --- | --- |
| L01 | 一个能访问的模型提供商、API配置与少量试验预算 | 让AI按官方SDK实现真实短请求；不把聊天订阅当API凭据 |
| L08 | 受限代码运行环境，Windows可考虑WSL2/Linux容器环境 | AI按你的系统生成准备步骤；docker version等基础检查之后，还要测网络/目录/进程边界 |
| L19 | 一个Python Web框架与本地持久数据库 | 锁定实际版本，测试创建、查询与重启 |
| J01 | JDK21、Maven、测试PostgreSQL | java -version、mvn -version、测试连接；实际版本记录入项目 |

L01给代码AI的是提供商名称、可用模型名、API地址类型与系统信息，不在聊天里粘贴真实密钥。密钥保存在本地环境；缺少真实配置的案例应明确blocked。
不要求你先安装尚未用到的所有服务；但进入L08执行代码前不能省略边界验证。

## 看不懂代码时怎么提问

给AI：“我有Java基础，请解释这个函数的输入、返回和一个失败分支，再给一个20行以内的可运行例子。不要改写整个模块。”
跑例子，修改一次输入并预测结果，然后回到当前课。每次只补当前阻塞知识。
