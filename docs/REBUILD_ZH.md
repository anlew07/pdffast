# PDFFast 全新开发环境重建与安全清理清单

**目标**：把开发仓库规范化为 \`pdffast\`，确认无需引用旧 V2/V3 虚拟环境即可安装并独立解析；**不是**清理 JudgeAI 内嵌 PDFFast 的操作说明。

**重要：目前仍未完成“彻底清空本机所有 PDFFast 相关模型缓存后再完整重装”的实测验收。** Git 源码 + \`uv.lock\` 可重建 Python 包依赖，模型/私有样本/用户缓存另行管理，不能在安装前直接清理。

## 1. 删除前先盘点与备份（只检查，不删除）

- Git：确认要保留的提交已在远端，检查所有开发工作区的 \`git status --short\`、本地分支、Tag、未跟踪文件；不能将“main 已同步”当作旧目录全部文件可删除。
- 样本/真值：\`outputs/\`、\`benchmark/\`、本地 PDF、人工 GT、私有配置、历史 reference 对照路径；分别决定归档/保留/可以再生成。
- 模型与配置：\`~/.paddlex\`、\`~/.cache/huggingface\`、\`~/mineru.json\`、Marker/Surya/Datalab 用户级缓存和配置（路径取 \`configs/providers.json\` 当前值）。
- Indra：\`runtimes/indra/models/indra-ocr/\`、\`runtimes/indra/install_manifest.json\`、\`runtimes/indra/requirements.lock\` 与隔离 \`.venv\`。模型文件及 lock/manifest **不提交 Git**；需记录模型 Git revision、哈希与许可证后再决定如何重建。
- 其他：本地 SSH/Git 凭据、下载许可、系统字体和依赖；不要把凭据加入项目文档或 Git。

可先在当前开发仓库执行以下**只读**命令：

\`\`\`bash
git remote -v
git rev-parse HEAD
git status --short --untracked-files=all
git branch -a
git tag --list
find runtimes -maxdepth 3 -name 'install_manifest.json' -o -name 'requirements.lock'
\`\`\`

对每个准备删除的旧目录执行同样的 Git/数据盘点。模型缓存可能为 JudgeAI 和其他软件共享资源，**不能据目录名称直接判断可删**。

## 2. 三种不同的“重建成功”

| 级别 | 条件 | 结论 |
|---|---|---|
| A 源码/代码检查 | 全新 clone；独立主 .venv；import 与 unit/contract 测试 | 证明代码环境可重建 |
| B 现有模型缓存复用 | 全新 clone + 自己的虚拟环境 + 受控共享缓存；Provider preflight、单任务与真实 PDF 解析 | 证明不依赖旧开发仓库的虚拟环境 |
| C 真正从空缓存重新安装 | 缓存/权重来源合法可访问；固定 revision；下载/校验/全模型/真实 PDF 测试通过 | 才能宣称完整冷启动重建 |

**现在应先达到 B；没有 C 的证据前，不删除唯一的模型副本和配置。** A 的测试通过绝不等于 C。

## 3. 在并行的新目录进行验证

保留旧 \`pdffast-v3\` 等目录暂不动，先新克隆到隔离目录（完成后才考虑定名为 \`pdffast\`）：

\`\`\`bash
cd ~/Workspace
git clone https://github.com/anlew07/pdffast.git pdffast-cleancheck
cd pdffast-cleancheck
git rev-parse HEAD
uv python install 3.12
uv sync --frozen --python 3.12 --extra dev --extra service --extra runtime-main
.venv/bin/python -c "from pdffast import PDFFastParser; print('PASS: core import')"
.venv/bin/python -m pytest -q tests/unit tests/contracts
\`\`\`

随后准备三个独立 Worker：

\`\`\`bash
uv sync --frozen --python 3.12 --project runtimes/mineru
uv sync --frozen --python 3.12 --project runtimes/marker
uv sync --frozen --python 3.12 --project runtimes/docling
\`\`\`

这些命令会创建新独立虚拟环境；若其模型仍位于旧目录或用户缓存，必须检查配置引用，不能把“import 成功”误当成资源就绪。

## 4. 模型准备必须可追踪

- **RapidOCR**：部分 ONNX 权重随安装包提供；具体 SHA-256 以当前 \`configs/providers.json\` 为准。
- **PaddleOCR / PaddleOCR-VL**：依赖用户级 PaddleX 模型缓存；需要检查目录和配置声明的文件。
- **MinerU / Marker / Docling**：依赖独立 Python Worker 及相应外部模型/用户级缓存。某些配置仍保留带旧阶段名称的缓存子路径；这只是路径名称，是否独立于旧目录需实际检查。
- **Indra**：独立 \`runtimes/indra/.venv\` 和三类 ONNX 模型；按 [Indra 安装说明](indra_runtime.md)操作，固定已批准的 Hugging Face 模型 commit，保留 \`install_manifest.json\` 和哈希。模型许可证的商业使用条件必须先审核。

Indra 安装入口：

\`\`\`bash
INDRA_MODEL_REVISION=<approved_model_revision_sha> bash scripts/install_indra_runtime.sh
.venv/bin/python scripts/verify_indra_runtime.py --hashes --preflight
\`\`\`

占位符需换成实际批准的模型 revision。该命令可能访问网络、下载大量模型，并受授权约束；不要在无许可和不知流量成本时直接执行。**新目录内不能简单复用旧目录的 Python 虚拟环境**，但在确保权重来源、哈希、权限一致的前提下可以复用已批准的模型文件。

## 5. 验收独立运行

在新仓库中使用一份有权使用、可重复校验的真实 PDF：

\`\`\`bash
.venv/bin/python scripts/run_pipeline.py /absolute/path/to/sample.pdf \
  --project-root . --output-root outputs --run-id rebuild_default
\`\`\`

如果选择对 Indra 进行可选验收，另用 \`--provider-profile configs/profiles/production.indra-triple.json\`，不要把两条路线的结果混为一谈。

保存验收记录：项目 Git SHA、模型 revision/hash、Python 与包版本、Profile 摘要、PDF SHA-256、PASS/FAIL/SKIP、解析耗时、\`document.md\`/\`document.json\`/\`audit.json\` 路径、人工内容质量核验结论。

同时确认 \`pdffast-cleancheck\` 的代码/解释器不会引用旧 V2/V3 工程路径；必要时停用旧环境中的后台 Worker 后，再测试运行。**不要通过删除旧目录来冒险“验证是否依赖它”。**

## 6. 允许清理旧目录的门槛

只有以下各项确认后，才制定逐目录清理计划：远端 Git 完整；本地私有/未追踪数据已备份；关键模型没有唯一副本；新仓库不使用旧 venv/PYTHONPATH；完整真实 PDF 回归通过；JudgeAI 与其他项目依赖已排除；已记录恢复方法。

**本文件不提供递归删除命令。** 清理属于单独执行任务，需要指定明确路径、备份位置和验收证据。禁止误删 \`/Users/admin/Projects/JudgeAI/.runtime/pdffast\` 或共享模型缓存。

达到上述门槛后，可以将验证通过的新克隆目录作为长期 \`~/Workspace/pdffast\` 开发工作区；不要修改 \`pdffast\` Python 包名。
