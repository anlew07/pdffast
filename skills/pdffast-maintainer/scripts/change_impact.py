#!/usr/bin/env python3
"""Static PDFFast change impact: symbols, direct importers, test suggestions."""
from __future__ import annotations
import argparse,ast,json
from pathlib import Path
from project_index import scan,search

TESTS={
 "pdffast/parser.py":["tests/unit/test_parse_service.py","tests/unit/test_package.py"],
 "pdffast/config.py":["tests/unit/test_parse_service.py"],
 "pdffast/result.py":["tests/unit/test_output_governance.py"],
 "pdffast/native/":["tests/unit/test_generic_sections.py","tests/regression"],
 "pdffast/quality/":["tests/unit/test_evidence_quality_objects.py"],
 "pdffast/fallback/":["tests/unit/test_fallback_executor.py"],
 "pdffast/providers/":["tests/unit/test_provider_plugins.py","tests/unit/test_runtime_normalization.py","tests/provider/test_provider_contracts.py"],
 "pdffast/canonical/":["tests/unit/test_canonical_document_units.py","tests/regression"],
 "pdffast/render/":["tests/unit/test_document_unit_renderer.py","tests/regression"],
 "pdffast/audit/":["tests/unit/test_document_unit_audit.py","tests/regression"],
 "pdffast/service/":["tests/unit/test_service_shutdown.py"],
 "tools/provider_benchmark/":["tests/unit/test_provider_benchmark.py","tests/unit/test_provider_benchmark_report.py"]
}
def module_name(p):
    return p[:-12].replace("/",".") if p.endswith("/__init__.py") else p[:-3].replace("/",".")
def imports(path):
    try: tree=ast.parse(path.read_text(encoding="utf8"))
    except (SyntaxError,UnicodeError):return set()
    found=set()
    for x in ast.walk(tree):
        if isinstance(x,ast.Import):found.update(y.name for y in x.names)
        elif isinstance(x,ast.ImportFrom) and x.module:found.add(x.module)
    return found
def impact(root,topic):
    root=Path(root).resolve()
    if not 1<=len(topic)<=200:raise ValueError("topic length must be 1..200")
    index=scan(root);hits=search(index,topic)
    paths={h["file"] for h in hits};mods={module_name(p) for p in paths}
    importers=[]
    for m in index["modules"]:
        path=m["path"]
        if path in paths:continue
        if any(x==n or x.startswith(n+".") for x in imports(root/path) for n in mods if n):
            importers.append(path)
    tests=set()
    for path in paths|set(importers):
        for prefix,rel in TESTS.items():
            if path==prefix or path.startswith(prefix):
                tests.update(t for t in rel if (root/t).exists())
    return {"status":"LOCATED" if hits else "NOT_FOUND","topic":topic,"project_head":index["git_head"],
      "targets":hits,"direct_importers":sorted(importers),"recommended_tests":sorted(tests),
      "warning":"AST only; read real source/callers; tests are suggestions, not proven coverage"}
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root",type=Path,required=True);p.add_argument("--topic",required=True)
    p.add_argument("--out",type=Path)
    a=p.parse_args();result=impact(a.project_root,a.topic);content=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if a.out:a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(content,encoding="utf8")
    print(content,end="");return 0 if result["status"]=="LOCATED" else 2
if __name__=="__main__":raise SystemExit(main())