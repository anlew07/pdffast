# B06-A4 独立代码审查

## 首轮结论

BLOCKED

独立审阅者对 A0–A3 进行了只读检查。审查时沿 CLI 与 Python facade、ParseService、Preflight、Core、Provider、Canonical、Renderer、Audit、Builder、原子 Manifest 发布和独立验签重新追踪。生产路由、候选链、Quality Gate 和既有 Provider 核心保持原样。首轮发现如下。

| 编号 | 级别 | 代码证据 | 触发与影响 | 修复事项 |
| --- | --- | --- | --- | --- |
| EXC-01 | P1 | `pdffast/application/execution_contract.py:259`，`pdffast/application/production_preflight.py:79,226` | 锁定预检规范化 RapidOCR 模型路径，Builder 将以绝对路径为键的模型摘要写进外部回执，未尝试 RapidOCR 时也会暴露本机目录。 | 公开模型文件名及摘要，保持内部配置身份及指纹，并同步校验 Schema 和独立验签。 |
| EXC-02 | P1 | `pdffast/pipeline/runner.py:336–348` | 审阅者用实际 Canonical、Renderer 和 Audit 确认，仅有页标记和视觉占位符、零终态保留的结果可通过原门禁并误报 SUCCESS。 | 在版本化回执发布前验证 Renderer 与 Audit，并基于实际渲染内容拒绝占位符。 |
| EXC-03 | P2 | `pdffast/parser.py:43–66` | facade 构造配置失败发生在 ParseService 之前，Python 错误回执可能缺失有效 run_id。 | facade 在配置错误时保留原请求的合法 run_id。 |
| EXC-04 | P2 | `pdffast/fallback/executor.py:270–283`，`pdffast/pipeline/runner.py:388–395` | 多 Provider 运行后，关闭较早 Provider 失败时，结构化错误可能使用最后执行的 Provider 名称。 | 保留发生清理错误的真实 Provider，并标识 `provider_cleanup`。 |
| EXC-05 | P2 | `pdffast/application/execution_contract.py:58–93` | Builder 的路径检查和打开文件之间有并发目录变更窗口。独立生产验签采用固定目录描述符，Builder 仍依赖部署边界。 | 交付合同明确输入不可变、输出根目录可信且仅由本次受管进程写入，消费端固定目录并验证实际读到的字节。 |

以上行号指向首轮审查时的本地代码。审查阶段仅生成报告。当用户授权的独立整改轮完成后，须复审后才进入 A5。

## 最终独立复审结论

PASS WITH RISKS

- EXC-01 已关闭。真实形态的 RapidOCR 路径键在外部合同中投影为文件名，保留对应摘要。内部生产身份、配置指纹保持有效，Schema 拒绝绝对路径键，独立验签与原始预检身份比对通过。
- EXC-02 已关闭。版本化结果要求 Renderer 与 Audit 通过，并检查实际可用内容。复审用真实 Canonical 和 Renderer 验证空占位符和纯机器码抑制说明不能构成可用正文。实际渲染的标题和经验证的解码值仍计入正文。
- EXC-03 和 EXC-04 已关闭。有效 run_id 可在 Python facade 配置失败时保留，清理错误指向实际失败的 Provider。
- EXC-05 保留为 P2。输出根目录应由受管进程独占写入，消费者以固定目录描述符等方式核验同一批实际读取的字节。内部日志和旧兼容字段只供本机运维使用。

独立复审确认无开放 P0/P1，可进入 A5。首轮和过渡复审的 BLOCKED 记录保留以方便核对整改证据。
