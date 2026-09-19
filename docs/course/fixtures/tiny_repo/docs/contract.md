# 分页公共契约 v1
目标文件是pagination.py。函数签名page(items, page_no, size)不能改变。页码从1开始，size为正整数。
空输入返回空列表；超出末页返回空列表；最后一页不足size时返回余下项目。函数不修改items。
page_no和size只接受正整数，不接受True/False/浮点数；非法值抛ValueError。
reporting.py中的page负责报表，不属于本次修复范围。测试和本契约不得由修复Agent修改。
