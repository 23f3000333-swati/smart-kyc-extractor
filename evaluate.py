"""Field-level evaluation against data/ground_truth.json.

    python evaluate.py

Reads output/extractions_<mode>.json for every mode that has been run and
writes output/eval_report.md (accuracy split printed vs handwritten, every
mismatch, and an offline vs hybrid comparison). This is the ONLY module that
reads the ground truth.
"""
from __future__ import annotations

import json
import re

import config

MODES = ["offline", "hybrid", "llm"]


def norm(value: str) -> str:
    """Comparison normalisation: case, spaces, titles, punctuation, commas."""
    v = (value or "").upper()
    v = re.sub(r"\b(MR|MRS|MS|MISS)\b\.?", "", v)
    return re.sub(r"[^A-Z0-9<&]", "", v)


def evaluate(extractions: dict, truth: dict) -> dict:
    """Compare one run with the ground truth."""
    expected_types = truth["_files"]
    rows, cls_ok = [], 0
    for doc in extractions["documents"]:
        exp_type = expected_types.get(doc["file"], "?")
        cls_ok += doc["doc_type"] == exp_type
        for name, gt in truth.get(exp_type, {}).items():
            field = doc["fields"].get(name) if doc["doc_type"] == exp_type else None
            got = field["value"] if field else ""
            rows.append({"file": doc["file"], "doc_type": exp_type, "field": name,
                         "expected": gt, "got": got, "correct": norm(got) == norm(gt),
                         "handwritten": bool(field and field["handwritten"]) or
                         _is_handwritten(exp_type, name),
                         "confidence": field["confidence"] if field else 0.0,
                         "flagged": field["flagged"] if field else True})
    return {"rows": rows, "classification_correct": cls_ok,
            "classification_total": len(extractions["documents"])}


def _is_handwritten(doc_type: str, field: str) -> bool:
    return any(s.name == field and s.handwritten for s in config.FIELDS.get(doc_type, []))


def summary(rows: list[dict]) -> dict:
    """Accuracy overall / printed / handwritten, and flag quality."""
    def acc(sel):
        return (sum(r["correct"] for r in sel), len(sel))
    wrong = [r for r in rows if not r["correct"]]
    return {"all": acc(rows),
            "printed": acc([r for r in rows if not r["handwritten"]]),
            "handwritten": acc([r for r in rows if r["handwritten"]]),
            "wrong_but_flagged": sum(r["flagged"] for r in wrong),
            "wrong": len(wrong),
            "flagged": sum(r["flagged"] for r in rows),
            "correct_unflagged": sum(r["correct"] and not r["flagged"] for r in rows)}


def pct(pair: tuple[int, int]) -> str:
    c, n = pair
    return f"{c}/{n} ({100 * c / n:.1f}%)" if n else "n/a"


def main() -> None:
    truth = json.loads(config.GROUND_TRUTH.read_text())
    results = {}
    for mode in MODES:
        path = config.OUTPUT_DIR / f"extractions_{mode}.json"
        if path.exists():
            results[mode] = evaluate(json.loads(path.read_text()), truth)
    if not results:
        raise SystemExit("no output/extractions_<mode>.json found - run run.py first")

    lines = ["# Evaluation report", "",
             "Field-level exact match after normalisation (case, spaces, Mr./MR., "
             "punctuation, commas). Ground truth: `data/ground_truth.json`.", "",
             "## Mode comparison", "",
             "| metric | " + " | ".join(results) + " |",
             "|---|" + "---|" * len(results)]
    sums = {m: summary(r["rows"]) for m, r in results.items()}
    metrics = [("classification", lambda m: pct((results[m]["classification_correct"],
                                                  results[m]["classification_total"]))),
               ("all fields", lambda m: pct(sums[m]["all"])),
               ("printed fields", lambda m: pct(sums[m]["printed"])),
               ("handwritten fields", lambda m: pct(sums[m]["handwritten"])),
               ("fields flagged for review", lambda m: str(sums[m]["flagged"])),
               ("wrong fields caught by a flag", lambda m:
                f"{sums[m]['wrong_but_flagged']}/{sums[m]['wrong']}"),
               ("correct and auto-accepted (not flagged)",
                lambda m: str(sums[m]["correct_unflagged"]))]
    for label, fn in metrics:
        lines.append(f"| {label} | " + " | ".join(fn(m) for m in results) + " |")
    missing = [m for m in ("offline", "hybrid") if m not in results]
    if missing:
        lines += ["", f"_Not run yet: {', '.join(missing)} (hybrid needs GROQ_API_KEY in .env; "
                  "then `python run.py --mode hybrid && python evaluate.py`)._"]

    for mode, res in results.items():
        lines += ["", f"## Per-field results: `{mode}`", "",
                  "| doc_type | field | hw | expected | got | conf | flagged | ok |",
                  "|---|---|---|---|---|---|---|---|"]
        for r in res["rows"]:
            lines.append(f"| {r['doc_type']} | {r['field']} | {'H' if r['handwritten'] else 'P'} | "
                         f"`{r['expected']}` | `{r['got']}` | {r['confidence']:.2f} | "
                         f"{'yes' if r['flagged'] else 'no'} | {'✅' if r['correct'] else '❌'} |")
        wrong = [r for r in res["rows"] if not r["correct"]]
        lines += ["", f"**Mismatches ({len(wrong)})**: " + (", ".join(
            f"{r['doc_type']}.{r['field']}" for r in wrong) or "none")]
        silent = [r for r in wrong if not r["flagged"]]
        if silent:
            lines.append("**Wrong AND not flagged (silent errors)**: " + ", ".join(
                f"{r['doc_type']}.{r['field']}" for r in silent))
    out = config.OUTPUT_DIR / "eval_report.md"
    out.write_text("\n".join(lines) + "\n")
    for m in results:
        s = sums[m]
        print(f"{m:8s} all {pct(s['all'])}  printed {pct(s['printed'])}  "
              f"handwritten {pct(s['handwritten'])}  wrong-but-flagged "
              f"{s['wrong_but_flagged']}/{s['wrong']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
