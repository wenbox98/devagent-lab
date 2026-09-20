# Python够用速查：只补影响当前代码理解的语法

## 怎么使用

不要从头背完。读源码卡在哪一行，查对应小节，运行一个短例子后回主线。下列代码都是语言/测试机制例子，不是当前仓库的新实现。API依据Python 3.12官方文档，资料入口见文末。

## 1. Mapping、dict与模块

`Mapping[str, str]` 表示可按键读取的映射接口类型；dict是常见具体实现。类型提示不把普通对象自动转换成字典，也不在运行时验证所有键值类型。

一个`.py`文件是模块，可按职责放多个类/函数。config.py放配置对象、配置错误与加载函数是内聚组织，不必机械复制Java一类一文件。职责独立演进或文件难维护时再拆，不按类数量决定。

## 2. 推导式：先写生成什么，再写从哪里来

```python
names = {"provider": "DEVAGENT_PROVIDER", "model": "DEVAGENT_MODEL"}
values = {"DEVAGENT_PROVIDER": "  fixture  "}
loaded = {field: values.get(name, "").strip() for field, name in names.items()}
```

等价于：

```python
loaded = {}
for field, name in names.items():
    value = values.get(name, "")
    loaded[field] = value.strip()
```

`{key: value for ...}` 是字典推导式；`[value for ...]` 是列表推导式；`{value for ...}` 是集合推导式。不能删掉字典推导式的大括号保留原语法。普通for的代码块由缩进划分，推导式的生成表达式与for/if子句由括号整体构成。

`get(name, "")` 只有键缺失时返回空串；如果键存在但值是None，返回仍是None，继续`.strip()`会报错。当前环境变量读取遵循值为字符串的合同，测试不能把该合同偷换后仍期待自动清洗。

## 3. 函数定义与调用里的等号

定义 `def f(x=10)`：默认值。调用 `f(x=20)`：按参数名传值。两者位置不同、含义不同。

```python
def make(*, config=None, transport=None):
    return config, transport

assert make(transport="t", config="c") == ("c", "t")
```

单独的`*`强制后面的参数只能按名字传；没有`*`时许多普通参数仍然允许按名字传，也仍可换关键字顺序。它的好处是禁止容易混淆的位置传法，而不是“有*才支持关键字”。

Python运行时做调用参数绑定；不符合关键字限定会TypeError。IDE/类型检查器可能提前提示，但`config: ProviderConfig`这样的类型注解默认不强制运行时类型。

`**loaded` 在调用时把字典展开成关键字参数；`**kwargs` 在定义时收集未单独声明的关键字参数。键冲突或不被函数接受会报错，不会静默任选一个。

## 4. self、_内部属性与or

`self._config`类似Java的`this.config`，单下划线是内部使用约定，不是真正的private权限。

`a or b` 返回第一个真值对象，否则返回b；不是只返回布尔值。它会把空dict、0、False等也视为无值。如果语义是“仅None时用默认”，优先写：

```python
chosen = provided if provided is not None else default
```

给测试传`environ={}`应表示空环境，而不是因空dict为假就偷偷退回真实os.environ。

## 5. Protocol究竟贴在哪里

```python
from typing import Protocol

class Transport(Protocol):
    def post_json(self, url: str, timeout: float) -> dict:
        ...

class Adapter:
    def __init__(self, *, transport: Transport):
        self._transport: Transport = transport
```

Protocol定义结构，参数/变量注解指出需要该结构的位置。静态检查器在把某个对象传给这里时比较方法及兼容签名，不是扫描所有类强制继承。普通Python运行不会因此自动拦截不合格对象；Any或未类型化路径可能削弱检查。

运行时需要强制时，可显式验证或采用ABC，但ABC也不自动验证所有参数/返回语义。不要为当前小项目制造复杂继承树。

## 6. with并不是先执行代码体再触发管理器

```python
with A(), B(), C():
    work()
```

正常顺序：进入A→进入B→进入C→work→退出C→退出B→退出A。等价于嵌套with。`as x`取得的是上下文管理器`__enter__()`返回值，不保证就是A()本身。

异常发生时从内往外交给`__exit__`；是否抑制由各管理器决定。with不普遍等于捕获所有异常，也不启动线程。文件with通常用于关闭资源；subTest/patch/assertRaises各有自己的退出行为。

## 7. @contextmanager和yield：L02的_filesystem_errors

```python
from contextlib import contextmanager

@contextmanager
def translate_errors():
    try:
        yield
    except FileNotFoundError as exc:
        raise RuntimeError("not_found") from exc
```

进入with时执行到yield暂停，随后运行with代码块。块里抛出的异常会在生成器的yield位置重新抛入，所以周围的except可以翻译它。正常退出则从yield后继续。这个函数必须恰好yield一次；不是把with内容复制进函数，也不是yield返回之后函数永远结束。

当前L02 `_filesystem_errors()`只翻译文件系统异常；自己抛的FileAccessError不会被其中的OSError分支当作原生I/O错误再吞掉。`raise ... from exc`保留异常因果，最终日志可看到根因与边界错误。

## 8. enumerate、解包和Path的斜杠

```python
cases = [("auth", 7), ("timeout", 3)]
for index, (name, code) in enumerate(cases):
    print(index, name, code)
```

enumerate为每个元素增加从0开始的计数，不是序列化元组。for左边进行嵌套解包。

`Path("tmp") / f"{name}.jsonl"` 中`/`被Path定义为拼路径，不是除法；f-string先把name插入字符串。拼接不完成授权，后面仍需规范化与归属判断。

## 9. subTest与assertRaises分别做什么

`subTest(code=code)`中的参数是子测试标签，不是传给被测函数。普通unittest仍按循环顺序执行，不开多线程。发生受框架处理的子测试失败后可继续后续循环；成功子测试不保证默认报告逐项打印。

```python
for failure, expected in cases:
    with self.subTest(expected=expected.__name__):
        with patch("module.target", side_effect=failure) as mocked:
            with self.assertRaises(expected):
                call_real_outer_code()
        self.assertEqual(mocked.call_count, 1)
```

这是展示作用域的骨架，module.target不是实际可运行路径。断言在subTest内才属于该子测试。把最后一行放到subTest外，第一次断言失败就可能结束整个测试方法。

assertRaises要求代码抛指定异常或其子类；没抛是断言失败，抛不匹配异常则继续传播，通常记录为error。它不是接受全部异常。

## 10. patch替换的是什么

patch临时替换某个对象属性，不扫描替换源码字符串。普通同步目标默认通常是MagicMock，异步目标可能是AsyncMock；指定new则直接用提供的对象。

`side_effect=某异常`：调用时抛异常；函数：调用该函数；可迭代序列：依次取值，元素是异常时抛出。`return_value`指定返回值。它们经patch的`**kwargs`配置到生成的mock，所以在patch签名里不一定显式列出。

`wraps=真实函数`可记录调用并委托真实行为；同时设置return_value/side_effect会改变优先行为，不能以为wraps总会发请求。call_count数的是这个mock被调用几次，不是公网传输了几次或服务器执行了几次。

### 模块引用的容易错点

adapter.py若写`from urllib import request`，其request引用共享的urllib.request模块。patch `adapter.request.urlopen` 实际修改这个共享模块的urlopen属性，其他通过同一模块对象访问的代码也会受影响。它不只局限于“这个文件”。

另一个模块提前 `from urllib.request import urlopen` 绑定到旧函数的名字，通常不会跟着该属性替换。原则是patch实际查找位置，并理解该位置指向共享对象还是独立名字。离开with恢复属性，不代表期间其他线程绝不会观察到替换。

### 假响应还需要支持with

```python
from unittest.mock import MagicMock
response = MagicMock()
response.read.return_value = b'{"choices": []}'
response.__enter__.return_value = response
```

实际代码有`with urlopen(...) as response`时，普通Mock仅设置read不够，必须提供上下文管理协议。测试具体查目标签名时可用autospec；spec/spec_set限制属性形状，不自动证明业务语义。

patch自己的unsafe控制某些常见规格参数拼写检查；不要与Mock的unsafe（影响assert开头属性访问保护）混为一谈。当前课无需使用这些高级开关。

## 11. 字节、字符、token与子进程编码

文件二进制read返回bytes；decode('utf-8')产生str；len(str)不是token数。文本模式可能做换行转换；L02二进制读取后解码以保留CRLF。

Windows CLI测试要同时固定两端：

```python
proc = subprocess.run(
    command, capture_output=True, text=True, encoding="utf-8",
    env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=10
)
```

这是关键调用片段，需要先导入os/subprocess并定义command。父进程encoding指定解码；子进程环境指定Python标准输出编码。只改父端不能保证任意子程序输出都是UTF-8，非Python子进程应查其编码选项。

PyCharm源码文件编码与运行配置、Terminal的环境不是同一层。临时学习可在Run/Debug配置设PYTHONUTF8=1，命令行在当前会话设置；团队测试仍应显式约定通信编码。

## 官方查阅入口

[类型与Protocol](https://docs.python.org/3.12/library/typing.html)；[复合语句与with](https://docs.python.org/3.12/reference/compound_stmts.html)；[contextmanager](https://docs.python.org/3.12/library/contextlib.html)；[unittest](https://docs.python.org/3.12/library/unittest.html)；[mock/patch](https://docs.python.org/3.12/library/unittest.mock.html)；[subprocess](https://docs.python.org/3.12/library/subprocess.html)；[pathlib](https://docs.python.org/3.12/library/pathlib.html)。

查阅完成标准：能用一个输入说明当前代码会执行哪条分支，然后回到本课。不是把所有官方页面读完。
