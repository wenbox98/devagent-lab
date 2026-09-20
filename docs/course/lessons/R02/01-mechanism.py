"""机制实验：排名RRF、单路去重、禁止候选过滤。没有向量/重排服务。"""
import json

def fuse(rankings, allowed, k=60):
    if k < 0:
        raise ValueError("k must be nonnegative")
    scores = {}
    for ranking in rankings:
        seen = set()
        for rank, doc in enumerate(ranking, 1):
            if doc in seen:
                continue
            seen.add(doc)
            if doc not in allowed:
                continue
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))

def main():
    result = fuse([["A", "B"], ["B", "C"]], {"A", "B", "C"})
    assert result[0][0] == "B"
    once = fuse([["A"]], {"A"})
    duplicate = fuse([["A", "A"]], {"A"})
    assert once == duplicate
    denied = fuse([["SECRET", "A"]], {"A"})
    assert all(doc != "SECRET" for doc, _ in denied)
    print(json.dumps({"scope":"rank-fixtures-only", "order":[doc for doc,_ in result],
                      "duplicates_counted_once":True, "verified":True}))

if __name__ == "__main__":
    main()
