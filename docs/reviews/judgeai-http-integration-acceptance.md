# JudgeAI / PDFFast v3 隔离 HTTP 集成验收

## 1. 结论与范围

本轮真实 case_002 HTTP 合同通过，真实 JudgeAI 上传 → ReviewTask → Celery → PDFFast → 解析记录持久化 → 评审上下文链路通过。隔离测试 **79 passed，0 failed（1.37 秒）**。未执行 Qwen 或完整 AI 评审，不宣称业务评审完成。没有修改双方生产源码、环境文件、路由或接受策略。

具备继续进行隔离替换演练的条件；本轮不批准直接切换正式 v2。没有发现此解析集成链路的 P0 阻塞。case_003、完整 AI 评分和 Linux 离线部署不在本轮验证范围。

## 2. 环境和隔离

源码基线为 PDFFast refactor/v3 的 923d035、b075e25。PDFFast 使用仓库 `.venv/bin/python`（Python 3.12），JudgeAI 使用自身 `.venv/bin/python`（Python 3.14）；不借用 v2 解释器。

成功实验目录：`outputs/judgeai_http_integration_acceptance/run_33213ae38afc/`。

| 服务 | 独立端口 | PID | 收尾等待秒 |
|---|---:|---:|---:|
| PDFFast v3 | 56811 | 66767 | 0.128 |
| JudgeAI API | 56812 | 66854 | 0.237 |
| PostgreSQL | 56813 | 66817 | 0.073 |
| Redis | 56814 | 66833 | 0.075 |
| Celery solo Worker | 无 HTTP 端口 | 66868 | 1.001 |

新建独立 PostgreSQL cluster/database `judgeai_acceptance_33213ae38afc`，执行实际 Alembic migrations。独立 Redis 实例的 DB 0，不是共享 Redis 的 DB 0。队列 `acceptance_run_33213ae38afc` 通过私有 API/Worker 的内存配置显式路由，并以 `-Q` 限制消费。上传、解析产物和历史目录全部位于该实验目录。覆盖环境变量，不改根目录 `.env`；有效配置见 `effective-settings.json`。

实际关闭所有本轮启动的 Popen 句柄，四个端口均确认释放。JudgeAI `.env` 指纹和 Git 状态前后不变。没有向 8000/8010/8011 发测试请求，没有全局进程清理。首次两次实验分别遭遇测试 PostgreSQL Unix socket 路径超过 103 字节、Redis 继承 locale 无效；仅修正测试工具短 socket 路径和子进程 locale，保留失败记录。这不是产品兼容性失败。

## 3. 双方 HTTP 合同和 Canonical

源码依据：PDFFast `pdffast/service/app.py`、`pdffast/service/__main__.py`；JudgeAI `backend/app/integrations/pdffast_http_adapter.py`、`backend/app/core/config.py`。

实际 Adapter 使用同步 multipart POST `/parse`，字段 `file`，读取 `PDFFAST_BASE_URL`；默认 timeout 1800 秒，实验显式 300 秒。响应必须满足 schema_version=1.0、非空 run_id/markdown、canonical/audit 为对象。非 200、连接失败、timeout、坏 JSON、必需字段缺失均由 Adapter 转换为明确错误。

Canonical 1.1 与 HTTP 外层 1.0 是不同合同。当前 Adapter 将 Canonical 原样保存为 document.json，并未解析 document_units/sections/records；输出 DocumentParseResult.sections=[]。实际 v3 Canonical 保存一致性由新增测试验证。JudgeAI 的 `review_context_service` / `review_context.py`、`llm/prompt_context.py` 消费完整 Markdown，不深入消费 Canonical 1.1。review_tasks.py 中名为 canonical_json 的对象是请求幂等指纹，不是 PDF Canonical。

Audit.validation.pass=True 映射 PASSED，False 映射 NEEDS_REVIEW，缺失/非布尔为 UNKNOWN；仅保留有效字符串 warnings。Audit False 当前不是自动阻止评分的条件。PASS 不证明 OCR 逐字正确。

## 4. case_002 真实 HTTP

输入 `/Users/admin/Workspace/pdffast/benchmark/samples/real/case_002.pdf`，SHA256 `f93885a1b52ab66c70b9bbb4068e59c13d1d4750d2113fdceae59a9158010da7`，16 页。

/health HTTP 200。实际 JudgeAI Adapter 调用返回 HTTP 200：run_id `api_bcd18840a69a461ab4201b60126f70d8`，Markdown 14838 字符，Canonical 1.1，Audit PASS、warnings=[]。HTTP 合同探测墙钟 2.555 秒（包括客户端调用和保存校验，不等于全部模型纯推理）。实际走 Native + RapidOCR 单个区域增强任务，未运行整份 case_003。证据：`http-response.json`、`http-contract.json`、`pdffast.log`。

## 5. 真实异步链路和持久化

使用已有测试合法标识 TEST_TECHNICAL / BUSINESS_001 / TYPE_A、TECHNICAL 模式，以及实际 `backend/configs/review_rules/528_technical.json`，上传请求经过真实规则校验。标签版本为 `528-frozen-acceptance`，不是新编造评分规则。

主任务 `942550c3-25ed-4de4-8a59-0fe45116a9f1` 经真实 POST 创建和 Celery 执行，解析 run_id `api_c0ee62f3f4f94f89a3ac69b7171df9e0`；ReviewParseRecord `fad82d3e-454d-49bf-afae-390e2607ec5f`。原 PDF 哈希、存储 Markdown、Canonical、Audit 和 parse_result 校验通过。上下文使用的 Markdown 与保存文本完全一致（14838 字符），冻结规则 form_code=528，scoring_blockers=[]。

只在 execution_service 边界注入测试停止器：调用真实 build_review_prompt_context，保存上下文，然后抛出 `ACCEPTANCE_AI_BOUNDARY`。因此主任务最终 **FAILED（人为停止 AI，预期）**，review_result_count=0、llm_called=false。这验证了解析/上下文及异常持久化，不验证完整 AI 成功状态。环境同时将模型端点设为本地不可用地址，防止误触付费调用。没有修改生产任务逻辑。

证据：`async-verification.json`、`context_<task_id>.json`、`celery.log`、`judgeai.log`、`task-ids.json`。上下文提示“缺少可靠章节结构，使用完整 Markdown”，属于 Adapter 当前 sections=[] 行为，并非 v3 Canonical 损坏。

## 6. v2 / v3 内容对照

只读取历史 v2 目录 `/Users/admin/Workspace/pdffast-v2/outputs/service/api_5d32b95ffe0e4c1baac16faa0415fb02`，未调用 v2 服务。该输出 page_snapshot.jsonl 与本次 v3 **字节相同**，证明原生扫描观察一致；历史输入 PDF 本体/哈希未另行证实。

| 项目 | v2 冻结 | v3 本次 |
|---|---|---|
| Markdown 字符 | 14872 | 14838 |
| Canonical schema | 1.0 | 1.1 |
| Canonical records | 71 | 71 |
| paragraph / table_ref / image_ref | 59 / 11 / 1 | 59 / 11 / 1 |
| Audit | PASS，0 warnings | PASS，0 warnings |
| sections 分组 | 11 | 11（含首页未归属分组） |

逐条记录按相同顺序对照：仅 section_id、section_title、zone_type、stage10_resolution 变化，其余字段完整相等，包括 text、table record 内容、来源页、bbox、word indices 和阅读顺序。因此这个样本未发现正文/表格记录损失或顺序变化。不是所有 OCR 内容正确性的证明。

旧标题“第一章 基本信息”等改为 PDF 观察标题“一、基本信息”等；旧“封面”生成标题不再出现，首页内容保留；项目进度计划标题保留真实括号说明。v3 document_units=[]，JudgeAI 不依赖该字段；不可将空集合解释为整份文件已完成 DocumentUnit 归属。详细章节页范围和标题见 `content-comparison.json`。Markdown 长度差不能作为质量排名。

## 7. 失败、超时、取消与资源边界

实际运行已有 Adapter/文档合同/解析持久化/上下文/上传规则/runner/Worker reliability 测试，加 12 个 Adapter 故障合同用例，合计 79 passed。覆盖连接失败、非 200、timeout、坏 JSON、缺字段、错误外层版本、Audit false/unknown、warnings 过滤、局部写盘失败清理和 v3 Canonical 原样保存。

真实取消：第二个任务在 Worker 启动前取消后保持 CANCELLED，无解析记录；主任务 PROCESSING 时取消请求返回 HTTP 409。当前取消仅针对 PENDING，不会向 PDFFast 传播运行中取消。客户端 HTTP timeout 也不等于远端解析已终止；这是现有边界，应由集成方明确处理，不能以本轮故障 Mock 证明远端取消成功。

正常 Adapter 错误不会形成完整成功产物；写盘失败删除自己新建的局部目录，不清共享存储。真实 AI 边界异常被 runner 记录为 FAILED，日志/解析证据保留。Provider失败不必然成为 HTTP失败：只要当前策略得到合法最终结果，可 HTTP200；Audit PASS同样不是所有候选Provider均成功。

## 8. 测试入口和修改范围

新增 `tools/acceptance/judgeai_http_integration.py`（私有服务监督）、`judgeai_isolated_apps.py`（内存隔离队列和 AI 停止边界）、`judgeai_probe.py`（真实 Adapter/DB/上下文校验）、`test_judgeai_contract_faults.py`（12 个新故障用例），以及本报告。未修改生产代码、JudgeAI文件或 .env。

执行：`.venv/bin/python tools/acceptance/judgeai_http_integration.py`（需要本地端口权限）。它复制 9 个已有测试文件到实验目录，再以 JudgeAI 自己 Python 执行 pytest -q -p no:cacheprovider --confcutdir <隔离tests> --basetemp <隔离pytest_tmp>。原因：原 backend/tests/conftest.py 含会对配置数据库删除 User/Item 的 session fixture，不能对共享开发数据库运行。实验只在自己新建数据库及各测试自建 SQLite 上操作。

本轮实际 79 passed / 0 failed，无完整 PDFFast 440/460 重跑。440 passed、20 skipped / reference 460 passed 是此前冻结基线，不冒充本轮结果。git diff --check 在收尾执行。真实进程退出、端口释放和原环境不变见 execution.json。

## 9. 风险、阻塞和下一轮

- P0：本次范围内未发现。
- P1（正式替换前验收）：修复后 case_003 全量结果与业务材料人工核验尚缺；真实完整 AI 评审、业务评分一致性及 Linux 离线环境未验证，本轮不得据此宣称正式全面替换准备完成。
- P1（运行边界）：明确 JudgeAI长请求/PDFFast服务超时、运行中不能取消，以及 NEEDS_REVIEW 是否允许进入评分的业务政策。当前行为不由本轮擅改。
- P2：将来若上下文按 Canonical DocumentUnit/sections 组织材料，必须另立 1.1 消费合同；当前 opaque 保存兼容不能保证未来深读兼容。
- 质量限制：SupplementalEvidence 未自动进入正文；Acceptance/Audit 不保证人名、公式、化学式准确。当前 case_002 记录保持证据不可外推 case_003。

建议下一轮先批准少量业务规则下的完整 AI 评审验收及真实内容人工检查，再决定隔离地址切换演练。无需先修改当前 Adapter。未切换正式 JudgeAI 地址，未 push/merge/commit，全部已有实验文件保留。
