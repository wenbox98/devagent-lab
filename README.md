# devagent-lab：从L00开始的学习仓库

这是逐课演进的学习仓库，目前已实现 L00 基础模拟请求、错误分类、事件追踪和演示；尚不是完整 Code Agent。教材入口：docs/course/00-从这里开始.md。

环境：Python 3.12+，L00 仅用标准库，无需安装第三方依赖或配置 API 密钥。在项目根目录运行：

```powershell
python -m unittest discover -s tests -v
python -m devagent --task "  explain pagination  "
python -m devagent.demos.l00 --list-cases
python -m devagent.demos.l00 --case success
python -m devagent.demos.l00 --case timeout
python -m devagent.demos.l00 --case empty-response
python -m devagent.demos.l00 --case empty-task
python -m devagent.demos.l00 --case trace-append
```

应用入口支持 `--mode success|timeout|bad_response` 和 `--trace-path`。业务退出码：正常 0、输入无效 2、模型超时 3、响应无效 4、日志 I/O 失败 5。默认日志追加到 `.local/traces/runs.jsonl`。

输入先清洗首尾空白，最多接受 5000 个字符（不是 token 数）；超过限制返回 `input_too_long`、退出 2，不调用模型。Python 调用者可用 `run_task(..., max_chars=...)` 配置正整数上限。

L00 基线提交后，下次改动可用 `git diff HEAD -- devagent tests` 对比；查看最近提交用 `git show --stat HEAD`，查看其具体修改用 `git show HEAD -- devagent tests`。应用、测试、学习记录和 `docs/course` 教材均由当前仓库统一管理。

演示会创建并清理独立临时目录，观测结果与事件包含在输出 JSON 中；`verified` 来自实际检查。演示退出 0 表示案例预期满足，因此正确处理超时的演示也退出 0。退出 1 表示断言失败，2 表示环境阻塞。CLI 参数用法错误也由 argparse 返回 2。

受限环境若禁止系统临时目录写入，需要使用获准的执行环境；不能把 `trace_io` 当作业务测试通过。PowerShell 若中文显示异常，可先执行 `$env:PYTHONIOENCODING = "utf-8"`；JSONL 文件始终使用 UTF-8。

实际验证与待填写学习记录：docs/learning-records/L00.md。当前基础测试通过不代表独立练习或学习验收完成。

L01 增加可切换的真实供应商边界，默认仍使用 fake。真实模式只读取本地环境变量，不读取或提交 `.env`：

```powershell
$env:DEVAGENT_PROVIDER = "供应商标识"
$env:DEVAGENT_MODEL = "实际可用模型名"
$env:DEVAGENT_API_KEY = "本地密钥"
$env:DEVAGENT_API_BASE_URL = "OpenAI兼容API根地址"
$env:DEVAGENT_TIMEOUT_SECONDS = "30"
python -m devagent --client real --task "Reply with OK."
```

真实适配器仅执行一次请求，不自动重试。配置缺失、认证、限流、超时、响应解析和其他服务错误使用不同错误码；供应商未返回 usage 时，输入和输出 token 均为 `None`。

全程保留同一个Git仓库。密钥只在本地环境，运行产物在.local，不把真实业务数据提交。每课学习证据写docs/learning-records/课号.md，不由代码AI代写个人成绩。
