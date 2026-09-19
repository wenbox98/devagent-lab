"""真实RRF计算；输入排名是人工教学fixture，不是实测语义召回。"""
from collections import defaultdict

def rrf(rankings: list[list[str]], allowed: set[str], rank_constant: int = 60) -> list[tuple[str, float]]:
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        # 先授权过滤与路内去重，再对合格列表计名次。
        clean = list(dict.fromkeys(doc for doc in ranking if doc in allowed))
        for rank, doc in enumerate(clean, start=1):
            scores[doc] += 1 / (rank_constant + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))

def main() -> None:
    lexical_fixture = ["d1", "d2"]
    semantic_fixture = ["d2", "d3"]
    result = rrf([lexical_fixture, semantic_fixture], {"d1", "d2", "d3"})
    assert [doc for doc, _ in result] == ["d2", "d1", "d3"]
    assert abs(result[0][1] - (1 / 61 + 1 / 62)) < 1e-12
    protected = rrf([["d1", "d1", "secret"], ["d2"]], {"d1", "d2"})
    assert "secret" not in dict(protected)
    assert abs(dict(protected)["d1"] - 1 / 61) < 1e-12
    print([(doc, round(score, 6)) for doc, score in result])
    print("dedupe_and_acl: passed")
    print("semantic_rankings: synthetic_fixture_not_model_measurement")

if __name__ == "__main__":
    main()
