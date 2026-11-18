# PDFFast 故障排查入口（当前仓库）

本文件供现在的独立 \`pdffast\` 开发工作区使用；历史文档中的 V2/V3 绝对路径、\`.venv-mineru\` 等命名不是现行环境约定。

## 1. 先收集信息

\`\`\`bash
git rev-parse HEAD
git status --short
.venv/bin/python --version
.venv/bin/python scripts/run_pipeline.py --help
\`\`\`

每次复现记录输入 PDF SHA-256、run_id、Profile、最终状态和异常堆栈。解析诊断通常在：

\`\`\`text
outputs/<run_id>/diagnostics/logs/pipeline.log
outputs/<run_id>/result/manifest.json
outputs/<run_id>/result/audit.json
\`\`\`

\`manifest.json\` 可能在失败前已写入，不代表解析成功。30 秒心跳只证明运行进程仍活跃。

## 2. 常见问题速查

| 症状 | 建议检查 |
|---|---|
| \`ModuleNotFoundError\` / Python 版本错 | 主环境 \`.venv\` 是否为 3.12、\`uv sync --frozen\` 的 extras；不要从旧虚拟环境注入 PYTHONPATH |
| 缺少 Worker 包 | \`runtimes/mineru/.venv\`、\`runtimes/marker/.venv\`、\`runtimes/docling/.venv\`；对应子项目锁文件 |
| Indra 找不到 ONNX 模型 | \`runtimes/indra/models/indra-ocr\`、\`install_manifest.json\`、\`scripts/verify_indra_runtime.py --hashes --preflight\` |
| Provider disabled / closure 错 | \`configs/providers.json\` 的 \`runtime_enabled\`，路由 Profile 的四条链和 Registry 插件注册 |
| OCR 未按预期选中 Indra | CLI 是否显式传入 \`--provider-profile configs/profiles/production.indra-triple.json\`；默认路由不是 Indra 三模型 |
| \`ValueError: cannot write empty image\` | 裁剪证据框、DPI、\`pdffast/fallback/planner.py\` 与极小 bbox 回归测试 |
| Markdown 有缺失、表格错位 | 对照 \`document.json\` / \`audit.json\` / 实际来源证据；不能只看 Provider accepted |
| 进程关闭缓慢 | \`pdffast/service/app.py\` 生命周期与隔离 Worker；保留具体 run_id/退出日志 |

## 3. 模型与用户缓存

主 Python 依赖、隔离 Worker 和模型权重**不是同一层**。PaddleX 模型、Hugging Face 模型、MinerU 配置、Marker 的用户级缓存可能由多个项目共享。

先阅读 [环境重建与安全清理](REBUILD_ZH.md)，对照现行 \`configs/providers.json\` 和各安装脚本找缺失路径。不要为了修复 import 错误复制旧项目的 \`.venv\`，也不要在未核对许可和 revision 时打开无约束模型下载。

Indra 完整安装和哈希验证见 [Indra Runtime](indra_runtime.md)。

## 4. 问题仍未解决

按 [维护者手册](MAINTENANCE_ZH.md)记录最小复现、日志、Git SHA、PDF/配置摘要，定位到 Native、Quality、Fallback、Provider、Canonical 或 Audit 的责任模块，添加回归测试后修复。**不要把 Audit PASS 宣称为 OCR 全文准确。**
