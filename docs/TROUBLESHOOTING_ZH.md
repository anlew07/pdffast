# 常见问题排查

## 从哪里开始

先记录异常类型、`run_id`、`ParseExecutionError.run_dir` 和 `log_path`，再查看：

```text
<run_dir>/diagnostics/logs/pipeline.log
<run_dir>/result/manifest.json
```

`pipeline.log` 包含失败前的 Stage、Provider stdout/stderr 和 Python 日志。完整 traceback 应由
调用方通过 `logger.exception()` 记录，因为 Core 会保留原始异常链。

## 终端出现大量 Stage 输出

确认 Parser 没有设置 `capture_output=False`。默认值是 `True`，旧 Stage 的摘要和第三方库输出
会进入 `pipeline.log`。CLI 或业务 adapter 可以打印自己的简洁状态，但不要直接调用内部 Stage。

## 找不到 Provider

先区分两类问题：

- 配置错误：Frozen policy 引用的 Provider 不在 runtime-enabled Registry 中，启动校验会直接失败；
- 运行环境错误：Provider 已启用，但其 Python 包、解释器或模型 artifact 不存在。

生产闭包只有 `rapidocr_ch_light`、`paddleocr_v5_mobile`、`paddleocr_vl_16`、
`mineru_local`、`marker_local`、`docling_local`。benchmark-only Provider 不应为了排错临时加入
生产 Registry。

## 模型或缓存缺失

PDFFast 的 Python 环境和模型缓存相互独立：

- Python 包安装在 `.venv` 或对应的 `.venv-mineru`、`.venv-marker`、`.venv-docling`；
- Paddle/PaddleX 模型复用 `~/.paddlex`；
- Hugging Face 模型复用 `~/.cache/huggingface`；
- Marker 还复用用户级 Datalab cache；
- RapidOCR ONNX 权重随 package 提供。

不要把旧项目 `.venv` 加到解释器路径，不要把模型复制进 Git 仓库，也不要在排查时允许自动
下载。先根据错误中的缺失路径，对照
[Provider 环境说明](PROVIDER_RUNTIME_ENVIRONMENTS.md)和
[Provider 验证记录](PROVIDER_RUNTIME_VALIDATION.md)检查已有 cache。

## 有内部 Stage 文件，是否代表 minimal 失效

不是。第一版 `minimal` 只收窄公共返回值，不删除内部文件。内部文件仍用于本次流水线后续阶段、
回归比较和失败复盘。业务方只需要使用 `result/`。

## 解析成功但结构不符合预期

依次检查：

1. `result/audit.json` 的 `validation`；
2. `result/document.json` 中的 Canonical 记录；
3. `full` 模式下的 `quality_gate`、`runtime_policy` 和 `production_manifest`；
4. 是否使用了预期的 Frozen route 和生产 Provider 配置。

不要通过调整阈值或 escalation 顺序临时绕过问题。保留该次 `run_dir`，用 reference-bound 回归
确认是输入差异、Provider 输出差异还是 Core 行为变化。

## 测试显示 SKIP

外部样本、旧工程路径或 Provider 环境缺失时，部分测试会跳过。`SKIP` 只说明前置条件没有提供，
不能作为真实 Provider、reference parity 或完整 PDF 解析通过的证据。
