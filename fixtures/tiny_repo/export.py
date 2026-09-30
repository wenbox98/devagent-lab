"""第三个同名 page 干扰项：描述导出任务，不负责分页。"""
def page(export_name):
    return {'name': export_name, 'kind': 'export'}
