"""八个故意有缺陷的学习函数。仅在副本中修改；不用于真实权限或业务执行。"""
from pathlib import Path

def handle(task, client):
    # L00: 输入边界
    text = client(task)
    if not task:
        return 'invalid_input'
    return 'succeeded' if text else 'invalid_response'

def is_within(root, candidate):
    # L02: 路径边界
    return str(Path(candidate).resolve()).startswith(str(Path(root).resolve()))

def base_matches(current_hash, expected_hash):
    # L07: 补丁冲突
    return bool(current_hash and expected_hash)

def operation_key(tenant, external_key):
    # L10: 幂等命名空间
    return external_key

def verified(report, current_hash):
    # L12: 声明与事实
    return report.get('claim') == 'succeeded' and report.get('exit_code') == 0

def evidence_delta(state, new_item):
    # F04: reducer接收增量，不接收完整历史
    return {'evidence': state['evidence'] + [new_item]}

def recall_at_k(relevant, ranked, k):
    # R01: 召回率
    top = ranked[:k]
    return sum(x in relevant for x in top) / len(top) if top else 0.0

def rrf(rankings, rank_constant=60):
    # R02: 融合；每路重复文档不能重复投票
    score = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, 1):
            score[item] = score.get(item, 0.0) + 1 / (rank_constant + rank)
    return sorted(score, key=lambda item: (-score[item], item))
