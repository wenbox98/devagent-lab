"""受控练习：故意保留分页偏移错误，直到L07/L09才修复。"""
def page(items, page_no, size):
    if type(page_no) is not int or type(size) is not int or page_no < 1 or size < 1:
        raise ValueError('page_no and size must be positive integers')
    start = page_no * size  # 故意错误；第一页编号为1。
    return items[start:start + size]
