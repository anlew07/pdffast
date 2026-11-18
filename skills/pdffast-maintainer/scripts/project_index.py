#!/usr/bin/env python3
"""Static Python AST code index of PDFFast: source paths, classes, functions, imports."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOTS = ("pdffast", "tools/provider_benchmark", "scripts")
MAP = {
 "pdffast/parser.py":"Python 公开入口 PDFFastParser.parse",
 "pdffast/config.py":"ParserConfig 参数与配置",
 "pdffast/result.py":"ParseResult 结果合同",
 "pdffast/application/parse_service.py":"解析服务、Provider 与 Profile 加载",
 "pdffast/application/input_fingerprint.py":"PDF 输入指纹",
 "pdffast/pipeline/runner.py":"全链路对象化 Pipeline 总协调",
 "pdffast/pipeline/context.py":"运行上下文",
 "pdffast/pipeline/artifacts.py":"输出产物路径",
 "pdffast/native/":"原生文本/章节/表格/阅读顺序",
 "pdffast/quality/evidence.py":"内容证据",
 "pdffast/quality/gate.py":"OCR/布局增强 Quality Gate",
 "pdffast/fallback/planner.py":"待增强任务准备",
 "pdffast/fallback/router.py":"四类 Capability Route",
 "pdffast/fallback/policy.py":"Provider 候选链/回退政策",
 "pdffast/fallback/executor.py":"Provider 执行/结果选择",
 "pdffast/providers/base.py":"Provider 接口、Task、RawResult",
 "pdffast/providers/registry.py":"Provider 显式注册和创建",
 "pdffast/providers/profiles.py":"四路线 Profile 配置",
 "pdffast/providers/runtime_normalization.py":"Raw Provider→CanonicalPrediction",
 "pdffast/providers/normalization.py":"CanonicalPrediction schema",
 "pdffast/providers/minicpm_ocr.py":"MiniCPM 可选插件 Adapter",
 "pdffast/providers/minicpm_normalizer.py":"MiniCPM 可选插件 Normalizer",
 "pdffast/providers/":"OCR/版面引擎与 Worker",
 "pdffast/canonical/":"规范文档构建",
 "pdffast/structure_reconciliation/":"跨页结构裁决",
 "pdffast/render/llm_ready.py":"LLM-ready Markdown",
 "pdffast/audit/":"结构/证据 Audit",
 "pdffast/service/app.py":"HTTP /health 与 /parse",
 "tools/provider_benchmark/prepare.py":"同一 DPI OCR 视觉输入",
 "tools/provider_benchmark/run.py":"Provider 真实 Benchmark",
 "tools/provider_benchmark/report.py":"同页 HTML/CSV 结果比较",
 "tools/provider_benchmark/evaluate.py":"审核 GT 的 CER/耗时评分",
 "scripts/run_pipeline.py":"正式 CLI 解析入口"
}
def responsibility(rel):
    if rel in MAP:return MAP[rel]
    matches=[k for k in MAP if k.endswith("/") and rel.startswith(k)]
    return MAP[max(matches,key=len)] if matches else "Read source to determine responsibility"
def git(root,*args):
    try:
        p=subprocess.run(["git","-C",str(root),*args],capture_output=True,text=True,timeout=5)
        return p.stdout.strip() if p.returncode==0 else None
    except (OSError, subprocess.TimeoutExpired):return None
def scan(root):
    root=Path(root).resolve()
    if not (root/"pdffast/parser.py").is_file():raise ValueError("pdffast/parser.py missing: not PDFFast repo")
    modules=[]
    for prefix in ROOTS:
        folder=root/prefix
        if not folder.is_dir():continue
        for path in sorted(folder.rglob("*.py")):
            if any(x in {".venv","__pycache__",".git"} for x in path.relative_to(root).parts):continue
            rel=path.relative_to(root).as_posix();raw=path.read_bytes()
            record={"path":rel,"sha256":hashlib.sha256(raw).hexdigest(),"responsibility":responsibility(rel)}
            try:
                tree=ast.parse(raw,filename=rel)
                symbols=[];imports=[]
                for n in tree.body:
                    if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                        symbols.append({"name":n.name,"line":n.lineno,"end_line":getattr(n,"end_lineno",n.lineno)})
                        if isinstance(n,ast.ClassDef):
                            symbols.extend({"name":n.name+"."+m.name,"line":m.lineno,"end_line":getattr(m,"end_lineno",m.lineno)}
                                           for m in n.body if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef)))
                    elif isinstance(n,ast.Import):
                        imports.extend(i.name for i in n.names if i.name.startswith("pdffast"))
                    elif isinstance(n,ast.ImportFrom) and (n.module or "").startswith("pdffast"):
                        imports.append(n.module)
                record.update({"symbols":symbols,"imports":sorted(set(imports))})
            except SyntaxError as exc:
                record["parse_error"]=str(exc)
            modules.append(record)
    return {"schema":"pdffast-source-index/v1","root":str(root),"head":git(root,"rev-parse","HEAD"),
            "branch":git(root,"branch","--show-current"),"files":len(modules),"modules":modules,
            "warning":"AST navigation only; verify actual source/callers and tests before change."}
def match(index,term):
    q=term.casefold()
    return [{"path":m["path"],"responsibility":m["responsibility"],
             "matching_symbols":[s for s in m.get("symbols",[]) if q in s["name"].casefold()]}
            for m in index["modules"]
            if q in m["path"].casefold() or q in m["responsibility"].casefold()
               or any(q in s["name"].casefold() for s in m.get("symbols",[]))]
def markdown(index):
    lines=["# PDFFast Static Code Index","",f"Head: {index['head']}","",f"Modules: {index['files']}","","| Path | Responsibility | Symbols |","|---|---|---|"]
    for m in index["modules"]:
        names=", ".join(f"{s['name']}:{s['line']}" for s in m.get("symbols",[]) if not s["name"].startswith("_"))[:160]
        lines.append(f"| \`{m['path']}\` | {m['responsibility']} | {names} |")
    return "\n".join(lines)+"\n"
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root",type=Path,required=True)
    p.add_argument("--topic")
    p.add_argument("--out",type=Path)
    a=p.parse_args()
    data=scan(a.project_root)
    if a.out:
        a.out.mkdir(parents=True,exist_ok=True)
        (a.out/"code_index.json").write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        (a.out/"code_index.md").write_text(markdown(data),encoding="utf8")
    print(json.dumps({"head":data["head"],"files":data["files"],
                      "matches":match(data,a.topic) if a.topic else None},
                     ensure_ascii=False,indent=2))
    return 0
if __name__=="__main__":raise SystemExit(main())
