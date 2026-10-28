# 原生文本 PDF 零增强任务计划修复

日期：2026-10-28。项目：`/Users/admin/Workspace/pdffast-v3`。
基线：`9598f6286773b02c0152fc02615d02aa83f7d253`。
修复分支：`fix/native-only-provider-plan`。

## PDF 与根因

样本：`/Users/admin/Downloads/judgeai_stage2_3cases/A_new_project.pdf`。
SHA256：`b4c8135bb830c6543de50da33c372b6184ed32b451e05c5996e6d63380c5b059`。

PDF 1.4，ReportLab 生成，2 页 A4（595.2756 × 841.8898 points）。
两页分别有 626、456 个原生字符，无图片，各有一条页脚横线。文本层可以正常抽取，第一页已渲染检查，标题、段落及中文显示正常。文件有效，不是扫描件、损坏文件或配置故障。

原失败运行：`api_8d5f6c6053934da689f33587c3a5cd9b`。
调用链：

`run_core_pipeline` → 原生解析/证据 → Stage8 `HARD_PASS / NATIVE_PASS` 两页、`NATIVE_COMPLETE`
→ `create_fallback_plan / collect_tasks`（没有需要 OCR、区域或上下文增强的内容，正确生成 0 个任务）
→ `create_capability_plan`（合法路由 0 个任务）
→ `create_provider_execution_plan / validate_provider_plan`（旧条件将空列表与缺失数据一起拒绝）
→ `ValueError: Provider plan tasks missing/empty`。

错误发生于约 0.1 秒，尚未调用 Provider。简短、干净的原生文本 PDF 恰好触发了此前未覆盖的零任务分支；不是短文档必须伪造 OCR 工作。

## 最小修改

生产代码只修改 `pdffast/fallback/policy.py` 的 `validate_provider_plan`：

- `tasks` 缺失、None 或不是 list，继续拒绝。
- 对空列表要求正整数 page_count，六项任务/路由/provider/重复统计必须明确为整数 0，两项类型/路由计数字典必须为空；布尔值、缺统计、计数冲突仍拒绝。
- 原版本、状态、任务 ID、重复与能力路由校验保留，候选 Provider 配置校验仍执行。
- 非空任务路径、Provider 选择、OCR、Stage8 与 Stage10 完全不变。
- 0 个增强任务不代表默认成功；仍由现有原生证据生成 Canonical/Markdown，再进行原质量审计。

新增 `tests/unit/test_native_only_provider_plan.py`，20 个回归：零任务对象传递与执行、17 个错误契约、真正两页原生 PDF 的完整 HTTP /parse 与产物一致性、零任务仍拒绝无效路由配置。测试中的 Provider/normalizer 禁止被调用，没有伪造成功 OCR 输出或替换解析结果。

## 验证

- 先失败：新增对象路径和真实 HTTP 路径均复现原 ValueError；17 个负向契约继续拒绝。
- 专项及路由/执行回归：28 passed。
- 修复前全量：465 passed，20 skipped。
- 修复后全量：485 passed，20 skipped。跳过项与原有条件一致（旧版参考目录、指定真实样本等未配置）。
- 原 89 页真实申报书运行 `api_31cb040eea05480b976525f6c7a71e74` 的 53 任务计划，用新代码重新构造的执行策略与原产物逐字段完全相同。未重复执行这份长文档的 OCR。
- 新测试 Ruff 通过；修改文件使用 Ruff E4/E7/E9/F 语法与导入检查通过，`git diff --check` 通过。未进行与本次无关的旧脚本风格整理。
- 独立只读审查未发现阻塞问题。

## 实际服务验证

确认 JudgeAI 使用的是 PDFFast v3 进程，原端口 8010；在无现有客户端连接时优雅停止旧服务，再以相同代码目录、输出目录、地址与端口启动修复版本，未强制杀进程。
当前验证进程 PID：40377。`GET /health` 返回 `{"status":"UP"}`。

直接将原 A PDF 上传至 `http://127.0.0.1:8010/parse`：

- HTTP 200；运行 ID `api_1466199d05a645b9abdec3217be1205f`。
- 2 页 HARD_PASS，文档 NATIVE_COMPLETE，0 个增强任务，0 次 Provider 调用。
- Markdown 1238 字符，包含真实受理编号 `S2026-JC-QN-1001` 及技术路线原文。
- 43 条原生段落完整进入 Canonical，原文顺序与内容检查通过。
- 审计 PASS，errors=[]、warnings=[]。
- 原 PDF 前后 SHA256 一致。

产物：

- `outputs/service/api_1466199d05a645b9abdec3217be1205f/result/document.md`
- `outputs/service/api_1466199d05a645b9abdec3217be1205f/result/document.json`
- `outputs/service/api_1466199d05a645b9abdec3217be1205f/result/audit.json`

本地诊断和测试日志：`/private/tmp/pdffast-native-plan-fix/`。不将日志、运行产物或用户 PDF 提交 Git。

可以重新执行 JudgeAI A 组测试。此结论针对 PDFFast 解析阻塞；本轮未发起 JudgeAI 评审任务，也没有承诺未执行的后续检索或评分结果。

## 边界与原有文件

本次仅修改上述 PDFFast 生产文件、新增回归与本报告。未修改 JudgeAI、历史案例数据或任何数据库，未调用 Qwen 评审。
原有 README.md 修改及 `:memory:.ses`、`docs/USER_GUIDE.md`、`experiments/`、`tools/acceptance/` 未被本次暂存或提交。未推送或合并分支。
