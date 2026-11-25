#!/usr/bin/env python3
"""Compare reading accuracy and segmentation independently; never changes extension files.

Setup (in a clone of the repo):
  npm install --no-save kuromoji@0.1.2
  python -m pip install sudachipy sudachidict_core
  python tests/compare_readings.py
Optional: install sudachidict_full and pass --dictionary full.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u9fff々〆ヶ]")
KATAKANA = str.maketrans({chr(c): chr(c - 0x60) for c in range(0x30a1, 0x30f7)})

def hira(s):
    return s.translate(KATAKANA)

def score(case, tokens):
    parts = []
    normalized = []
    for t in tokens:
        surface, reading = t["surface"], t.get("reading")
        if HAN.search(surface) and reading and reading != "*":
            reading = hira(reading)
            parts.append(f"{surface}（{reading}）")
            normalized.append(reading)
        else:
            parts.append(surface)
            normalized.append(hira(surface))
    output = "".join(parts)
    return {"output": output, "exact": output == case["expected"],
            "reading": "".join(normalized), "reading_match": "".join(normalized) == case["expected_reading"], "tokens": tokens,
            "source_preserved": "".join(t["surface"] for t in tokens) == case["text"]}

def kuromoji(cases):
    js = """
const k = require('kuromoji');
const fs = require('fs'), path = require('path');
const texts = JSON.parse(fs.readFileSync(0, 'utf8'));
const start = performance.now();
k.builder({dicPath:path.resolve('vendor/dict')}).build((err, engine) => {
 if(err){console.error(err);process.exitCode=1;return;}
 const loaded = performance.now();
 const rows = texts.map(text => engine.tokenize(text).map(t => ({
  surface:t.surface_form,reading:t.reading||'',unknown:t.word_type==='UNKNOWN'
 })));
 console.log(JSON.stringify({load_ms:loaded-start,tokenize_ms:performance.now()-loaded,rows}));
});
"""
    p = subprocess.run(["node", "-e", js], cwd=ROOT,
                       input=json.dumps([c["text"] for c in cases]),
                       capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(p.stdout)

def sudachi(cases, dict_type, mode):
    from sudachipy import dictionary, tokenizer
    start = time.perf_counter()
    engine = dictionary.Dictionary(dict=dict_type).create()
    loaded = time.perf_counter()
    rows = []
    for case in cases:
        rows.append([{"surface": t.surface(), "reading": t.reading_form(),
                      "unknown": t.is_oov()}
                     for t in engine.tokenize(case["text"], getattr(tokenizer.Tokenizer.SplitMode, mode))])
    return {"load_ms": (loaded-start)*1000,
            "tokenize_ms": (time.perf_counter()-loaded)*1000, "rows": rows}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dictionary", choices=["small", "core", "full"], default="core")
    args = parser.parse_args()
    cases = json.loads((ROOT/"tests/reading-corpus.json").read_text(encoding="utf-8"))
    engines = [("kuromoji", lambda: kuromoji(cases))]
    engines.extend((f"sudachi-{args.dictionary}-{m}", lambda m=m: sudachi(cases,args.dictionary,m)) for m in "ABC")
    report = {}
    for name, run in engines:
        try:
            raw = run()
            if len(raw["rows"]) != len(cases):
                raise ValueError("Unexpected number of tokenized cases")
            results = [{**case, **score(case,tokens)} for case,tokens in zip(cases,raw["rows"])]
            report[name] = {"load_ms":raw["load_ms"],"tokenize_ms":raw["tokenize_ms"],
                            "exact_matches":sum(r["exact"] for r in results),
                            "reading_matches":sum(r["reading_match"] for r in results),
                            "total":len(results),"cases":results}
        except Exception as exc:
            report[name] = {"error":str(exc)}
    print(json.dumps(report,ensure_ascii=False,indent=2))
    # A failed engine must not silently count as a successful benchmark.
    return int(any("error" in r for r in report.values()))

if __name__ == "__main__":
    raise SystemExit(main())
