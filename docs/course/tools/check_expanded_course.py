"""Check v5 teaching structure, not semantic correctness or learner mastery."""
from pathlib import Path
import json, re, sys
ROOT = Path(__file__).resolve().parents[1]

def inspect():
    coverage = json.loads((ROOT / "revision-coverage-v5.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "course-manifest.json").read_text(encoding="utf-8"))
    problems = []
    total = 0
    for entry in coverage["lessons"]:
        lesson = entry["lesson"]
        text = (ROOT / "lessons" / lesson / "01-教程.md").read_text(encoding="utf-8")
        topics = re.findall(r"^### K[0-9]+\.", text, re.M)
        total += len(topics)
        if len(topics) != entry["topic_count"]:
            problems.append(lesson + ": topic count differs")
        if text.count("**原教材的浓缩句：**") != len(topics):
            problems.append(lesson + ": missing original quote")
        for marker in ("一条具体方案", "怎样证明它有效", "代码现在在哪里", "独立练习", "本次只做这一步"):
            if marker not in text:
                problems.append(lesson + ": missing " + marker)
        if entry["code_status"] == "planned" and "不是当前基线已有源码" not in text:
            problems.append(lesson + ": future code status unclear")
        if entry["added_mechanism"] and not (ROOT / "lessons" / lesson / "01-mechanism.py").is_file():
            problems.append(lesson + ": mechanism missing")
    if [x["lesson"] for x in coverage["lessons"]] != manifest["order"]:
        problems.append("coverage order differs")
    result = {"status": "passed" if not problems else "failed", "lessons": len(coverage["lessons"]),
              "topics": total, "errors": problems,
              "scope": "Structural markers and mapping only; does not grade explanation quality."}
    return result

if __name__ == "__main__":
    result = inspect()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)
