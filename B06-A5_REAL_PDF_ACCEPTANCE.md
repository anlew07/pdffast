# B06-A5 真实 PDF 最小回归与 JudgeAI 交付验收

## 结论

**PASS。PDFFast Embedded Execution Contract V1 可进入 JudgeAI 联调。** 本次完成 PDFFast 侧真实 PDF 交付验收，以及真实 CLI 的结构化输入拒绝验证。JudgeAI 端全链路联调属于下一阶段。

## 输入与预检

| 文件 | 字节数 | SHA-256 | 本次执行 |
| --- | ---: | --- | --- |
| case_001.pdf | 3746750 | `2e5df92403daf3c1ba164dc2fcfd289e602676b78dfe3e6486230d97292b8862` | 输入和请求校验 |
| case_002.pdf | 1942963 | `f93885a1b52ab66c70b9bbb4068e59c13d1d4750d2113fdceae59a9158010da7` | 输入和请求校验 |
| case_003.pdf | 19146701 | `4769d5180d5e54f8e0d7bbac81f01bcb184dd428adbd2aac4bc20007c755328c` | 输入和请求校验 |
| case_004.pdf | 25173781 | `323b48f7293e0a8ff8d4378df64dea5da7bb3219966619d4734dee3965ac3cf4` | 输入和请求校验 |
| case_005.pdf | 6084236 | `97eddae80a997f85b2f32e421a3548732ccd5555f231b7b6000b5afdad87ddf7` | 输入和请求校验，真实 Embedded 端到端 |

- 五份输入位于 `/Users/admin/Workspace/resource`。分别重算 SHA-256，并用 Python Validator 和 Request Schema 校验。
- 扫描原项目输出和 OCR benchmark 中 161 份可读根 Manifest。历史回执中有同一批 PDF 的输入或溯源证据，但缺少新版执行合同，因此选择历史记录中六个 Provider 任务均成功的 `case_005.pdf` 做唯一一次实际解析。
- 使用已安装的 Core、Indra、MinerU 和 RapidOCR 环境。运行仓库的 `freeze_production_assets.py`，从现有模型读出 SHA 和 stat，在当前 worktree 生成 Indra、MinerU 两份缺失的只读 `model_assets_manifest.json`。现有模型、Provider 配置及路由保持原样。
- `production.indra-triple.json` 预检为 `PASS`，三个 Provider 均为 `READY`。常规预检的可选运行时探测为 `NOT_RUN`。正式解析另走 Core 自身的预检。

## 真实 CLI 与回执

从 `/Users/admin/Workspace/pdffast-v3-worktrees/execution-contract-v1` 执行的调用如下。重现时将变量设为样本 PDF 和新的私有输出根目录。

```bash
.venv/bin/python -B -m scripts.run_pipeline "$pdf" \
  --project-root "$PWD" \
  --provider-profile "$PWD/configs/profiles/production.indra-triple.json" \
  --output-root "$output_root" \
  --run-id b06-case005 \
  --expected-input-sha256 97eddae80a997f85b2f32e421a3548732ccd5555f231b7b6000b5afdad87ddf7
```

| 检查 | 实际结果 |
| --- | --- |
| CLI、回执与 Audit | 退出码 0，状态 `SUCCESS`，20 页，Audit PASS，独立生产验签 PASS。 |
| Provider | 计划 6 任务，实际尝试及选中 `indra_local` 均为 6 次。Indra 版本 `1.1.2`，模型 revision `bd02167fdf2005a19962cc15188f8496a2c87d3b`。0 次未解决失败、0 次终态保留、0 次未批准尝试。 |
| 输入和根 Manifest | 实际 PDF、请求、stdout 合同、根 Manifest 的输入 SHA-256 一致。stdout 合同与根 Manifest 嵌套合同一致。 |
| 产物 | 从固定 run 目录读取并重算 12 个交付产物的 SHA-256 和字节数。覆盖 Canonical、Markdown、Audit、Production Manifest、策略、索引及六份任务证据。 |
| 公开路径 | stdout 回执通过 Success Schema，递归检查没有本机绝对路径。 |
| 失败回执 | 对同一份 PDF 传入错误摘要，CLI 退出码 2，回执 `BLOCKED / INPUT_SHA256_MISMATCH` 通过 Error Schema。没有创建该失败任务的 run 目录。 |
| 执行身份 | 配置指纹 `c8e28434506f06b129e7f9ef96c7a34cbfb4b893c00c58467d80d2879b4c2d26`，源码 SHA-256 `f590ac5298f4a3698eabf85bde305fc712565375058e8d3a23689d4cb64cd55f`。 |

- Markdown SHA-256 为 `2f1be69d8523bf530557c8f9d960fe103726d08b44eaf86a7b372b9cff0269b0`。
- 根 Manifest 独立 SHA-256 为 `399a7bad2d2499cfdf4482817e9242b20f084d05e62e725c5efe2f94d479553c`。
- 成功及失败 JSON、预检和独立验签记录保存在验收机器的私有证据目录。该目录及 PDF 产物属于本地验收记录。

## 最终本地测试与差异

- A5 当时默认离线全集为 **673 通过、1 个已复现的基线失败、19 跳过、61 未选中**。合并前补齐 MinerU 测试夹具后复跑 **674 通过、0 失败、19 跳过、61 未选中**。A4 后合同、Provider、预检、Canonical 与 CLI 重点回归 **102 项通过**。三份 Schema 和 Git 差异检查通过。
- 相对本地原始 HEAD `ef225cfb560a03a6f70a90bcf59e929120ec15b4`，最终 Git 差异涉及 20 个已跟踪文件，覆盖合同、请求/错误接线、产物门禁、Observer、CLI、独立验签、开发依赖和测试。另有两份新 Schema、A0 至 A5 报告、JudgeAI 交付文档和两份本地资产清单。原有用户未提交修改保留。
- 本次真实样例仅执行 Indra。RapidOCR 与 MinerU 通过生产预检，未为增加样本覆盖另跑 OCR。Provider 初始化失败、回退、取消和部分成功使用本地注入及回归验证。
- 合并前已修复 MinerU 生命周期测试夹具。A4 留有部署侧 P2 限制，输入须保持不变，输出目录须可信且只由受管进程写入。真实回执记录 `PDFFAST_SOURCE_DIRTY` 与 `PROVIDER_DEPENDENCY_PROBE_NOT_RUN`。本次证据属于未提交的本地候选版本。
- 进入 JudgeAI 联调时使用 [Embedded Execution Contract V1](docs/integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)，保留本次回执和身份验证门禁。
