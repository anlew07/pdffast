# P1-1：PDF 输入指纹与字节数

## 范围

仅实施已批准 P1-1；未实施 Provider 原生证据留存、内容风险检测或内容选择调整。保留此前未提交工作，没有提交、清理、重启服务或重跑完整 case_003。

## 实现

共同入口 `ParseService.parse` 在 Provider 配置加载和 Native 分析之前，以 1 MiB 分块读取实际输入文件，计算 SHA-256，累计实际读到的字节数。HTTP 上传临时文件与直接 Parser 调用均经过该入口。不保存原始 PDF 副本，也不记录 PDF 内容。

使用现有 `ArtifactPaths.result.manifest_json`，即 `<output_root>/<run_id>/result/manifest.json`，先保存 run_id 和 input 元数据；配置或 Pipeline 随后失败时，这份记录仍在。通过 `PipelineContext.input_metadata` 直接传对象，最终结果写出时保留同一 input 字段。不为后续计算回读 Manifest。

示例结构：

```json
{
  "run_id": "example",
  "input": {
    "algorithm": "sha256",
    "sha256": "实际读取字节的64位十六进制摘要",
    "byte_size": 123,
    "filename": "input.pdf",
    "status": "COMPLETE"
  }
}
```

HTTP 场景 filename 是实际临时文件名 input.pdf；原始业务文件名仍由既有 case_id/服务合同管理，不声称此字段是上传展示文件名。最终 Manifest 的原有 result、case_id 等字段保持，input 为新增字段。早期 Manifest 仅是输入记录，不代表解析完成。

读取失败记录 `status=FAILED`、`sha256=null`、`byte_size=null` 和原始异常类型/信息；不伪装为零字节，不替换既有解析错误处理。合法空文件的摘要采集可以 COMPLETE、大小为 0，但这不代表该文件是有效 PDF；HTTP 原有非空检查保持。

## 兼容性和边界

- HTTP v1、ParseResult、Canonical、Markdown、Audit、Acceptance、Router、心跳不变。
- 同次运行对象传递不新增 Runtime File Bus。
- 这是扫描前读到的字节摘要，不是文件全生命周期快照。直接调用者必须保持输入不变；本轮没有实现前后变更检测、解析后复核或私有复制。
- 未回填历史运行指纹，不能借当前参考文件 SHA-256 证明历史上传字节。
- 新增一次线性文件读取，内存用量按块有界；本轮未测大型真实 PDF 的额外墙钟耗时。
- 写诊断目录失败会暴露文件系统异常，不能保证无权限/磁盘满情况下仍持久化。
- 未更改同 run_id 重用行为；不同并发解析应继续使用各自独立 run_id。

## 修改文件

1. `pdffast/application/parse_service.py`：流式摘要和早期 Manifest。
2. `pdffast/pipeline/context.py`：向后兼容的可选 input_metadata。
3. `pdffast/pipeline/runner.py`：最终 Manifest 保留输入记录。
4. `tests/unit/test_input_fingerprint.py`：6 项测试，覆盖空文件、小文件、跨块文件、输入缺失、配置失败、最终 Manifest。
5. 本报告。

以上与工作区原有日志降噪修改分开，未覆盖其文件。

## 实际验证

先运行新增测试，确认缺少 input_metadata 失败；随后增加配置失败测试，确认早期记录缺失失败，再完成实现。

`uv run` 首次因沙箱无法访问 `/Users/admin/.cache/uv` 而未能启动；改用当前 v3 的 `.venv/bin/python -m pytest`，未借用旧仓库 Python。

| 实际命令/范围 | 结果 |
|---|---|
| input_fingerprint + parse_service 专项 | 8 passed |
| `.venv/bin/python -m pytest -q tests/unit tests/contracts tests/regression` | 449 passed、30 skipped、0 failed，27.51 秒 |
| 设置 PDFFAST_REFERENCE_ROOT 与 PDFFAST_SAMPLE_PDF 后同一全套 | 469 passed、10 skipped、0 failed，133.92 秒 |
| 获准在沙箱外补跑 `tests/unit/test_service_shutdown.py`，隔离端口 | 10 passed，7.79 秒 |
| `git diff --check` | 通过 |

无 reference 的 30 个跳过包含 20 个参考数据依赖和 10 个 localhost bind 受限场景；reference-bound 的 10 个均因沙箱禁止监听。后者已单独补跑通过；不将合并数字声称为单次全套结果。

完整回归包括现有 HTTP 合同、对象 handoff、Renderer/Audit、Supplemental 与 Provider 测试；未新增真实 HTTP PDF 推理或模型任务。最终新增测试断言整理后再次执行专项 8 passed。

## 下一步

等待独立批准 P1-2 原生证据有界留存。本轮指纹功能不会修复 OCR 姓名、公式或缺句，也不会把 SupplementalEvidence 自动插入正文。
