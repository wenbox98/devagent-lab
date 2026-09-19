"""独立尝试之后才阅读。受控教学参考，不是生产安全库。"""
from pathlib import Path

def handle(task, client):
    if not isinstance(task, str) or not task.strip():
        return 'invalid_input'
    try:
        text = client(task.strip())
    except TimeoutError:
        return 'model_timeout'
    if not isinstance(text, str) or not text.strip():
        return 'invalid_response'
    return 'succeeded'

def is_within(root, candidate):
    root, candidate = Path(root).resolve(), Path(candidate).resolve()
    return candidate.is_relative_to(root)

def base_matches(current_hash, expected_hash):
    return isinstance(current_hash, str) and bool(current_hash) and current_hash == expected_hash

def operation_key(tenant, external_key):
    if not tenant or not external_key:
        raise ValueError('empty namespace or key')
    return (tenant, external_key)

def verified(report, current_hash):
    count, passed = report.get('collected'), report.get('passed')
    return (report.get('exit_code') == 0 and type(count) is int and count > 0
            and type(passed) is int and passed == count
            and report.get('snapshot_hash') == current_hash
            and report.get('scope_ok') is True)

def evidence_delta(state, new_item):
    return {'evidence': [new_item]}

def recall_at_k(relevant, ranked, k):
    if type(k) is not int or k < 0:
        raise ValueError('k must be a nonnegative integer')
    relevant = set(relevant)
    if not relevant:
        return None  # 无相关文档的任务单列拒答指标，不把它算成Recall=1
    return len(relevant & set(ranked[:k])) / len(relevant)

def rrf(rankings, rank_constant=60):
    if type(rank_constant) is not int or rank_constant < 0:
        raise ValueError('rank_constant must be a nonnegative integer')
    score = {}
    for ranking in rankings:
        for rank, item in enumerate(dict.fromkeys(ranking), 1):
            score[item] = score.get(item, 0.0) + 1 / (rank_constant + rank)
    return sorted(score, key=lambda item: (-score[item], item))
