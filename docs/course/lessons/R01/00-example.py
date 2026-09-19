"""真实BM25数值教学；只支持明确的英文/代码token，不是embedding。"""
import math
import re
from collections import Counter

def tokens(text: str) -> list[str]:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).replace("_", " ")
    return re.findall(r"[a-z0-9]+", text.lower())

def bm25(query: str, docs: dict[str, str], k1: float = 1.5, b: float = 0.75) -> list[tuple[str, float]]:
    if not docs:
        return []
    counts = {key: Counter(tokens(text)) for key, text in docs.items()}
    lengths = {key: sum(c.values()) for key, c in counts.items()}
    average = sum(lengths.values()) / len(lengths) or 1.0
    result = []
    for key, terms in counts.items():
        score = 0.0
        for term in set(tokens(query)):
            df = sum(term in c for c in counts.values())
            idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
            tf = terms[term]
            if tf:
                score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * lengths[key] / average))
        if score > 0:
            result.append((key, score))
    return sorted(result, key=lambda item: (-item[1], item[0]))

def main() -> None:
    docs = {"d1": "pagination page size offset", "d2": "thread pool queue timeout", "d3": "validate input page"}
    ranking = bm25("pagination page", docs)
    assert ranking[0][0] == "d1"
    assert bm25("quantum", docs) == []
    assert bm25("page", {}) == []
    print([(key, round(score, 4)) for key, score in ranking])
    print("no_answer:", bm25("quantum", docs))

if __name__ == "__main__":
    main()
