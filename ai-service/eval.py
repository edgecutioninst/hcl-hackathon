"""Evaluation of the extractor against the sample truth file + output files for the evaluation set.

python eval.py            # writes ../output/{evaluation_report.md, extraction_output.csv, ai_decisions_output.csv}
python eval.py --misses   # also prints every wrong field (development aid)
"""

from __future__ import annotations

import collections
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from app.extractor import (
    DATA_DIR,
    DOC_TYPES,
    RULES_VERSION,
    classify,
    extract,
    noise_score,
)  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
FIELDS = [
    "name",
    "dob",
    "gender",
    "pan_number",
    "aadhaar_last4",
    "address",
    "pincode",
    "document_date",
    "valid_until",
]
REQUIRED = {
    "PAN_CARD": ["name", "dob", "pan_number"],
    "AADHAAR_CARD": ["name", "dob", "aadhaar_last4"],
    "ELECTRICITY_BILL": ["pincode", "document_date"],
    "BANK_STATEMENT": ["pincode", "document_date"],
    "DRIVING_LICENCE": ["pincode", "valid_until"],
}
CLEAN_BANNER = "SYNTHETIC SPECIMEN - NOT A VALID DOCUMENT"


def texts(split):
    return {
        j["doc_id"]: j["text"]
        for j in map(
            json.loads,
            (DATA_DIR / f"case_02_document_text_{split}_V1.0.jsonl")
            .read_text()
            .splitlines(),
        )
    }


def norm(f, v):
    v = (v or "").strip()
    return re.sub(r"\s+", " ", v.upper()) if f in ("name", "address") else v


def keyword_baseline(text):  # organiser-style single-keyword rule
    t = text.upper()
    for kw, ty in [
        ("ELECTRICITY", "ELECTRICITY_BILL"),
        ("PERMANENT ACCOUNT", "PAN_CARD"),
        ("AADHAAR", "AADHAAR_CARD"),
        ("DRIVING", "DRIVING_LICENCE"),
        ("STATEMENT", "BANK_STATEMENT"),
    ]:
        if kw in t:
            return ty
    return "OTHER"


def regex_only(text, doc_type):
    """First version: plain regexes, no OCR repair, no lexicon (baseline for AI-2)."""
    out = {}
    if m := re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", text):
        out["pan_number"] = m[1]
    if m := re.search(r"X{4} X{4} ([0-9]{4})", text):
        out["aadhaar_last4"] = m[1]
    if m := re.search(r"PIN:? ([1-9][0-9]{5})|- ([1-9][0-9]{5})", text):
        out["pincode"] = m[1] or m[2]
    if m := re.search(r"(?:Date of Birth\n|DOB: )(\d\d)/(\d\d)/(\d{4})", text):
        out["dob"] = f"{m[3]}-{m[2]}-{m[1]}"
    if m := re.search(r"(?:Valid Till: )(\d\d)/(\d\d)/(\d{4})", text):
        out["valid_until"] = f"{m[3]}-{m[2]}-{m[1]}"
    if m := re.search(r"(?:Statement Date: )(\d\d)/(\d\d)/(\d{4})", text):
        out["document_date"] = f"{m[3]}-{m[2]}-{m[1]}"
    if m := re.search(r"Bill Date: (\d\d)-(\w{3})-(\d{4})", text):
        mon = [
            "JAN",
            "FEB",
            "MAR",
            "APR",
            "MAY",
            "JUN",
            "JUL",
            "AUG",
            "SEP",
            "OCT",
            "NOV",
            "DEC",
        ]
        if m[2].upper() in mon:
            out["document_date"] = f"{m[3]}-{mon.index(m[2].upper()) + 1:02d}-{m[1]}"
    if m := re.search(r"\b(MALE|FEMALE)\b", text):
        out["gender"] = m[1][0]
    if m := re.search(r"(?:Name\n|Consumer Name: |Name: )(.+)", text):
        out["name"] = m[1].strip()
    return out


def main(show_misses=False):
    truth = {
        r["doc_id"]: r
        for r in csv.DictReader(
            (DATA_DIR / "case_02_document_truth_sample_V1.0.csv").open()
        )
    }
    st = texts("sample")
    labels = [t for t in DOC_TYPES]
    conf_m = collections.Counter()
    cls_ok = kw_ok = 0
    per = collections.defaultdict(lambda: [0, 0])
    per_clean = collections.defaultdict(lambda: [0, 0])
    per_poor = collections.defaultdict(lambda: [0, 0])
    rx = collections.defaultdict(lambda: [0, 0])
    acc_hi = [0, 0]
    acc_lo = [0, 0]
    misses = []
    for d, tr in truth.items():
        text = st[d]
        r = extract(text)
        conf_m[(tr["doc_type"], r.doc_type)] += 1
        cls_ok += r.doc_type == tr["doc_type"]
        kw_ok += keyword_baseline(text) == tr["doc_type"]
        poor = CLEAN_BANNER not in text
        got = {f.field_name: f for f in r.fields}
        base = regex_only(text, tr["doc_type"])
        for f in FIELDS:
            if not tr[f]:
                continue
            g = got.get(f)
            ok = bool(g) and norm(f, g.value) == norm(f, tr[f])
            for bucket in (per, per_poor if poor else per_clean):
                bucket[f][0] += ok
                bucket[f][1] += 1
            rx[f][0] += norm(f, base.get(f)) == norm(f, tr[f])
            rx[f][1] += 1
            if g:
                b = acc_hi if g.confidence >= 0.80 else acc_lo
                b[0] += ok
                b[1] += 1
            if not ok:
                misses.append(
                    (
                        d,
                        tr["doc_type"],
                        f,
                        tr[f],
                        g.value if g else None,
                        round(g.confidence, 2) if g else None,
                        poor,
                    )
                )
    n = len(truth)

    # ---- evaluation-set outputs
    et = texts("eval")
    OUT.mkdir(exist_ok=True)
    with (OUT / "extraction_output.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["doc_id", "field_name", "value", "confidence"])
        for d in sorted(et):
            r = extract(et[d])
            w.writerow([d, "doc_type", r.doc_type, f"{r.doc_type_confidence:.2f}"])
            for f in r.fields:
                w.writerow([d, f.field_name, f.value, f"{f.confidence:.2f}"])
    # Same mock extraction for sample (for AI decisions on sample vs expected)
    with (OUT / ".extraction_sample_ai.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["doc_id", "field_name", "value", "confidence"])
        for d in sorted(st):
            r = extract(st[d])
            w.writerow([d, "doc_type", r.doc_type, f"{r.doc_type_confidence:.2f}"])
            for f in r.fields:
                w.writerow([d, f.field_name, f.value, f"{f.confidence:.2f}"])
    backend = ROOT / "backend"
    data = lambda n_: str(DATA_DIR / f"case_02_{n_}_V1.0.csv")  # noqa: E731
    subprocess.run(
        [
            "node",
            "batch.js",
            data("applications_eval"),
            data("documents_eval"),
            str(OUT / "extraction_output.csv"),
            str(OUT / "ai_decisions_output.csv"),
        ],
        cwd=backend,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "node",
            "batch.js",
            data("applications_sample"),
            data("documents_sample"),
            str(OUT / ".extraction_sample_ai.csv"),
            str(OUT / ".ai_decisions_sample.csv"),
        ],
        cwd=backend,
        check=True,
        capture_output=True,
    )

    # Decisions with AI extraction on the sample vs. expected (mock) and vs. what the truth file implies
    exp = {
        r["application_id"]: r
        for r in csv.DictReader(
            (DATA_DIR / "case_02_applications_sample_V1.0.csv").open()
        )
    }
    ai_dec = {
        r["application_id"]: r
        for r in csv.DictReader((OUT / ".ai_decisions_sample.csv").open())
    }
    same = [a for a in exp if ai_dec[a]["decision"] == exp[a]["expected_decision"]]
    diff = [
        (
            a,
            exp[a]["expected_decision"],
            exp[a]["expected_reason_codes"],
            ai_dec[a]["decision"],
            ai_dec[a]["reason_codes"],
        )
        for a in exp
        if a not in same
    ]

    # Fairness: NAME_MISMATCH_MINOR share by gender (eval set, AI decisions)
    apps_eval = {
        r["application_id"]: r for r in csv.DictReader(open(data("applications_eval")))
    }
    fair = collections.defaultdict(lambda: [0, 0])
    for r in csv.DictReader((OUT / "ai_decisions_output.csv").open()):
        g = apps_eval[r["application_id"]]["gender"]
        fair[g][1] += 1
        fair[g][0] += "NAME_MISMATCH_MINOR" in r["reason_codes"].split("|")
    ai_eval = {
        r["application_id"]: r
        for r in csv.DictReader((OUT / "ai_decisions_output.csv").open())
    }
    mock_eval = (
        {
            r["application_id"]: r
            for r in csv.DictReader((OUT / "decisions_output.csv").open())
        }
        if (OUT / "decisions_output.csv").exists()
        else {}
    )
    inj = [d for d in et if "PROMPT_INJECTION_TEXT" in extract(et[d]).flags]

    tot_ok = sum(v[0] for v in per.values())
    tot = sum(v[1] for v in per.values())
    rx_ok = sum(v[0] for v in rx.values())
    pct = lambda a, b: f"{100 * a / b:.1f}%" if b else "n/a"  # noqa: E731
    L = [
        f"# OnboardIQ extraction evaluation\n",
        f"Extractor `{RULES_VERSION}` (deterministic rules + OCR repair + reference-lexicon name repair; no LLM). "
        f"Development and scoring on the {n} sample documents with `case_02_document_truth_sample_V1.0.csv`. The evaluation set has no truth, so only its outputs are produced.\n",
        "## AI-1 Classification\n",
        "| Method | Accuracy |",
        "|---|---|",
        f"| Declared doc type (customer choice) | {pct(sum(1 for d in truth if declared_type(d) == truth[d]['doc_type']), n)} |",
        f"| Single-keyword rule baseline | {pct(kw_ok, n)} |",
        f"| **OnboardIQ classifier** | **{pct(cls_ok, n)}** |\n",
        "Confusion matrix (rows = truth, columns = predicted):\n",
        "| truth \\ pred | " + " | ".join(labels) + " |",
        "|---" * (len(labels) + 1) + "|",
    ]
    for t in labels:
        L.append(f"| {t} | " + " | ".join(str(conf_m[(t, p)]) for p in labels) + " |")
    L += [
        f"\nPrompt-injection document(s) in the evaluation set: {', '.join(inj) or 'none'} -> classified OTHER (flag PROMPT_INJECTION_TEXT). "
        f"A2100100 AI decision: `{ai_eval.get('A2100100', {}).get('decision')}` `{ai_eval.get('A2100100', {}).get('reason_codes')}`.\n",
        "## AI-2 Field extraction (exact match after normalisation)\n",
        "| Field | All | Clean scans | Poor scans | Regex-only v1 |",
        "|---|---|---|---|---|",
    ]
    for f in FIELDS:
        if per[f][1]:
            L.append(
                f"| {f} | {pct(*per[f])} ({per[f][1]}) | {pct(*per_clean[f])} | {pct(*per_poor[f])} | {pct(*rx[f])} |"
            )
    cl_ok = sum(v[0] for v in per_clean.values())
    cl = sum(v[1] for v in per_clean.values())
    po_ok = sum(v[0] for v in per_poor.values())
    po = sum(v[1] for v in per_poor.values())
    L += [
        f"| **overall** | **{pct(tot_ok, tot)}** ({tot}) | {pct(cl_ok, cl)} | {pct(po_ok, po)} | {pct(rx_ok, tot)} |\n",
        f"Poor scans = documents whose specimen banner is damaged by OCR ({sum(1 for d in truth if CLEAN_BANNER not in st[d])} of {n}).\n",
        "## AI-4 Confidence calibration\n",
        "| Confidence band | Fields | Correct | Precision |",
        "|---|---|---|---|",
        f"| >= 0.80 (used by rules) | {acc_hi[1]} | {acc_hi[0]} | {pct(*acc_hi)} |",
        f"| < 0.80 (sent to officer) | {acc_lo[1]} | {acc_lo[0]} | {pct(*acc_lo)} |\n",
        "Officer corrections are stored as `ExtractedField` rows with `source = OFFICER`, `reason`, `createdBy` and the superseded value kept inactive; "
        "`SELECT count(*) FILTER (WHERE source='OFFICER') / count(DISTINCT \"documentId\")` gives the correction rate per document for re-training.\n",
        "## Decisions with AI extraction\n",
        f"Sample set: {len(same)}/{len(exp)} applications get the same decision as the expected (mock-extraction) column. Differences:\n",
        "| Application | Expected (mock) | AI extraction |",
        "|---|---|---|",
    ]
    for a, ed, er, ad, ar in diff:
        L.append(f"| {a} | {ed} {er} | {ad} {ar} |")
    if mock_eval:
        changed = sum(
            1
            for a in ai_eval
            if ai_eval[a]["decision"] != mock_eval.get(a, {}).get("decision")
        )
        L.append(
            f"\nEvaluation set: {changed}/{len(ai_eval)} decisions differ between the mock extraction (`decisions_output.csv`) and our extraction (`ai_decisions_output.csv`)."
        )
    L += [
        "\n## Fairness: NAME_MISMATCH_MINOR by gender (evaluation set, AI decisions)\n",
        "| Gender | Applications | NAME_MISMATCH_MINOR | Share |",
        "|---|---|---|---|",
    ]
    for g, (k, m) in sorted(fair.items()):
        L.append(f"| {g} | {m} | {k} | {pct(k, m)} |")
    ext = collections.defaultdict(dict)
    for r in csv.DictReader((OUT / "extraction_output.csv").open()):
        ext[r["doc_id"]][r["field_name"]] = r["value"]
    docs_eval = collections.defaultdict(list)
    for r in csv.DictReader(open(data("documents_eval"))):
        docs_eval[r["application_id"]].append(r["doc_id"])
    L.append(
        "\nName normalisation is identical for everyone (titles removed, token order ignored). Flagged cases:\n"
    )
    for a, r in ai_eval.items():
        if "NAME_MISMATCH_MINOR" in r["reason_codes"].split("|"):
            read = sorted(
                {ext[d].get("name") for d in docs_eval[a] if ext[d].get("name")}
                - {apps_eval[a]["full_name"]}
            )
            L.append(
                f"- {a} ({apps_eval[a]['gender']}): declared `{apps_eval[a]['full_name']}`, document shows `{', '.join(read)}` (score {r['name_match_score']})"
            )

    # Held-out check: no truth for the eval set, so compare with the mock extraction where the mock is confident.
    mock = collections.defaultdict(dict)
    for r in csv.DictReader(
        (DATA_DIR / "case_02_extraction_mock_eval_V1.0.csv").open()
    ):
        mock[r["doc_id"]][r["field_name"]] = (r["value"], float(r["confidence"]))
    agree = total = 0
    for d, fs in mock.items():
        for f, (v, c) in fs.items():
            if c >= 0.80:
                total += 1
                agree += norm(f, ext[d].get(f)) == norm(f, v)
    L += [
        "\n## Held-out sanity check (evaluation set)\n",
        f"The sample scores above are on the development set the rules were tuned on, so they overstate expected accuracy. On the evaluation set "
        f"(not used for tuning, no truth file) our values agree with {agree}/{total} ({pct(agree, total)}) of the mock extraction's own confident (>= 0.80) values; "
        "inspected disagreements are mostly OCR misreads in the mock (e.g. `8engaluru`, `Flat 1Z`) that our repair corrects, plus a few poor-scan addresses we score below 0.80.",
    ]
    (OUT / "evaluation_report.md").write_text("\n".join(L) + "\n")
    for p in (OUT / ".extraction_sample_ai.csv", OUT / ".ai_decisions_sample.csv"):
        p.unlink(missing_ok=True)
    print(
        f"classification {pct(cls_ok, n)} (keyword {pct(kw_ok, n)}); fields {pct(tot_ok, tot)} clean {pct(cl_ok, cl)} poor {pct(po_ok, po)}; precision>=0.80 {pct(*acc_hi)}; sample decisions same {len(same)}/{len(exp)}"
    )
    if show_misses:
        for m in misses:
            print("MISS", *m)
        for d in diff:
            print("DIFF", *d)


_declared = None


def declared_type(doc_id):
    global _declared
    if _declared is None:
        _declared = {
            r["doc_id"]: r["declared_doc_type"]
            for r in csv.DictReader(
                (DATA_DIR / "case_02_documents_sample_V1.0.csv").open()
            )
        }
    return _declared.get(doc_id)


if __name__ == "__main__":
    main("--misses" in sys.argv)
