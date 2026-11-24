# PDFFast 生产解析配置身份 V1

合同版本为字符串 `"1.0"`，配置 Schema 与 [provenance Schema](parser_provenance.v1.schema.json) 独立解析。当前是 PDFFast 工作树上的待合入合同。部署应从最终合入的发布源码与固定运行时重新生成身份并更新 JudgeAI 的部署 pin。

## Core 与 CLI

```python
from pathlib import Path
from pdffast import PDFFastParser, ParserConfig, preflight_production_profile

root = Path("/srv/pdffast")
config = ParserConfig(
    project_root=root,
    provider_profile=root / "configs/profiles/production.indra-triple.json",
    output_root=Path("/srv/parse-runs"),
    output_mode="minimal",
)
report = preflight_production_profile(config=config)
if report["status"] != "PASS":
    raise RuntimeError(report["status"])
# 父进程应在调度解析前校验预检返回的部署 pin。
result = PDFFastParser(config=config).parse(Path("/srv/input/input.pdf"), run_id="unique-run-id")
```

```bash
/path/to/core/python -m pdffast.preflight \
  --project-root /srv/pdffast \
  --provider-profile /srv/pdffast/configs/profiles/production.indra-triple.json \
  --json
```

`preflight_production_profile(*, project_root=None, provider_profile=None, config=None, probe=False) -> dict` 接受一份 `ParserConfig` 或传入两个路径。CLI 对应默认解析参数。调整 DPI 或表格模式时，请用 Python API 在预检与解析之间共用配置。两种入口使用同一加载和预检逻辑。Core 解析会重新预检，并仅使用其当次已验证的 Profile、Provider 配置和冻结路由快照。外部预检结果须与最终 provenance 对照。

预检默认只检查配置、安装文件以及包元数据。使用 `--probe` 或 `probe=True` 额外运行 Provider 的依赖导入探测，依赖探测与推理分别记录。常规 CLI 调用在 stdout 输出一个 JSON 对象。参数或配置不合法返回 `2`，环境或身份检查失败返回 `3`，`PASS` 返回 `0`。`--help` 是常规帮助入口。

## 配置选择与安全

显式 `project_root` 时读取其 `configs/providers.json` 和 `configs/frozen/stage9_route_candidates_prod_v001.json`。省略 `project_root` 时使用包内对应资源。绝对 Profile 路径直接使用，相对路径以显式项目根或已加载 PDFFast 的项目根为基准。部署方控制仓库、配置、运行时和模型目录的写权限。

Profile 是四条执行链与允许 Provider 集合的来源。已启用的名字须匹配随代码发布的适配器和插件绑定。锁定调用拒绝自定义 registry、Provider 配置、插件、normalizer 和 routes overrides。使用 `PDFFastParser(config=...)` 时，锁定相关设置应全部放入 `ParserConfig`。历史默认模式省略 `provider_profile`，继续使用历史路由行为，V1 锁定身份和 provenance 缺省。

## 预检字段

| 字段 | 类型和约束 |
| --- | --- |
| `schema_version` | 字符串 `"1.0"` |
| `status` | `PASS`、`CONFIGURATION_FAILED`、`PREFLIGHT_FAILED` |
| `profile_locked` | 在可形成锁定身份时为布尔值 `true` |
| `profile_name`、`profile_path`、`providers_config_path` | 非空字符串。路径供诊断 |
| `profile_sha256`、`providers_config_sha256` | 对实际读取的原始字节分别计算的 64 位小写十六进制 SHA-256 |
| `effective_config_fingerprint` | 对 `fingerprint_input` 的规范化 SHA-256。预检失败时为 `null` 或缺省 |
| `allowed_providers` | 有序且唯一的 Provider 名称数组，顺序取自 Profile |
| `capability_routes` | 四个固定能力键组成的对象，值为非空有序 Provider 名称数组 |
| `pdffast_commit` | 实际所加载代码仓库的 Git HEAD。无 Git 元数据的发行包为 `null` |
| `code_identity` | `pdffast_commit`、`source_sha256`、`source_dirty` 和 `algorithm_sha256`。安装包的 Git dirty 状态为 `null` |
| `fingerprint_input` | 指纹的可重算输入对象 |
| `provider_runtime` | 按已选 Provider 列出的状态、依赖探测结果和模型身份 |
| `inference_performed` | 报告含完整配置身份时为 `false` |
| `error` | 某些失败分支提供的诊断字符串。调用方按 `status` 处理 |

[配置身份 JSON Schema](production_parser_identity.v1.schema.json) 是结构合同。失败报告允许缺省字段，JudgeAI 以已配置的 Schema 版本和 `PASS` 作为接入条件。兼容扩展可以增加字段，V1 已定义字段的语义、算法或必选条件改变时须发布新版本并隔离缓存。

## 指纹计算

```python
import hashlib
import json

encoded = json.dumps(
    report["fingerprint_input"], sort_keys=True, separators=(",", ":"),
    ensure_ascii=False, allow_nan=False,
).encode("utf-8")
assert hashlib.sha256(encoded).hexdigest() == report["effective_config_fingerprint"]
```

使用 Python JSON 数据类型。对象键排序，数组顺序保留，缺省字段与显式 `null` 依照报告本身编码。配置加载拒绝重复键与非标准数值。有效 Provider 配置先按 registry 的路径规则展开，路径规范为绝对路径且保留虚拟环境解释器链接的调用语义。环境选项与有效 Provider 配置的内部哈希使用同一规范化规则。每次锁定预检加载 Profile 时捕获一次进程环境。锁定路径、Provider 配置变量、隔离 Provider 的元数据探测、依赖探测与执行都使用该快照。隔离 Provider 接收已解析的环境覆盖值。Core 在进入流水线和发布 manifest 前核对影响结果的当前进程环境摘要，变化使执行失败。环境摘要纳入以下前缀的实际键值对，`MINERU_`、`INDRA_`、`ORT_`、`OMP_`、`MKL_`、`OPENBLAS_`、`VECLIB_`、`HF_`、`HUGGINGFACE_`、`TRANSFORMERS_`、`TORCH_`、`PYTORCH_`、`CUDA_`、`MPS_`、`UV_`、`DYLD_`、`LD_`。

`fingerprint_input` 固定包含 Schema 版本、两份原始配置哈希、冻结候选文件原始哈希、允许名单、四条路线、适配器及 normalizer 绑定、每个已启用 Provider 的有效配置哈希、源码身份、解析选项、运行时身份、主机运行时信息及相关环境变量哈希。主环境和隔离环境的可读包版本清单各自归一化为包名到版本的映射，再提供清单哈希及关键包版本。Native 依赖另列为 `core_dependencies`，预检同时核对其包导入位置。隔离 Provider 的依赖探测和执行使用与元数据探测一致的 Python 隔离模式。运行时身份纳入模型 revision、安装清单或本地配置摘要与验证级别。供诊断的探测结论、路径字段 `profile_path` / `providers_config_path`、Git dirty 布尔值及输出目录、run ID、输出模式、日志捕获设置在指纹输入之外。当前 `rapidocr_workers` 只在配置及上下文流转，执行器按既有 wave 执行，因此它也在指纹输入之外。

`source_sha256` 对实际加载的 PDFFast 包目录下所有 `*.py` 的相对 POSIX 路径到文件内容 SHA-256 的有序映射求哈希。各算法 SHA-256 使用相同规则，对 Native、Evidence、Quality、Fallback、Canonical、Renderer、Audit 与结构重协调的源文件分别分组。内容指纹包含包内未提交的源码改动，即使 HEAD 一致也会改变。Git 身份绑定已加载包所在 checkout，独立于调用进程继承的 Git 仓库变量。`source_dirty` 取该 checkout 的 `pdffast/`、`configs/`、`scripts/run_pipeline.py`、`pyproject.toml` 与 `uv.lock` 路径的 Git 状态。生产 CLI 未提交的改动会使 `source_dirty=true`，已提交的 CLI 内容由发布 Commit 绑定。发布门禁还应核对整个 checkout。源码字节、路径及分组一致时，`source_sha256` 跨提交保持相同。发布 Commit 改变时，内外层 `pdffast_commit` 同步改变，纳入指纹的 Commit 使有效指纹随之改变。来自另一个 checkout 的配置与已加载包的代码身份分别追踪。生产环境应在不可变部署中启动新解释器，并保持输入 PDF、运行时、模型、环境变量和依赖在预检及解析期间稳定。包版本清单验证元数据，第三方包源码、原生库和权重目录的完整物理证明需要部署侧完整性控制。

`LD_LIBRARY_PATH` 的启动值仍进入配置指纹和锁定 Worker 环境。Core 进程内的 OpenCV 导入可能更新该变量以影响后续子进程；锁定 Worker 消费已捕获值，因此 Core 的运行中漂移检查忽略此变量的进程内变化。

## 模型与环境

在安装或更新 Indra / MinerU 模型后，必须在目标部署 checkout 中执行一次 `python -B scripts/freeze_production_assets.py`。脚本只读取本地模型，不下载或修改模型文件；它校验 Indra 安装 Manifest 的 SHA，并为两个模型目录生成只读的 `model_assets_manifest.json`。普通预检将清单 SHA、模型文件 SHA 声明和文件 stat 纳入运行时身份，并在 Provider 创建、Worker 启动、每次执行前后及关闭时重新比较 stat。这样不需要每次解析重复读取 GB 级权重。正式发布验收另执行 `python -B -m pdffast.preflight --project-root "$PWD" --provider-profile "$PROFILE" --verify-assets --json`，显式重算所有冻结模型文件的 SHA-256。模型文件发生任何常规替换或修改后，必须重新冻结并重新批准身份。

| Provider | 预检依据 | 模型字节验证 |
| --- | --- | --- |
| Indra | checkout 独立 Python、`indra-ocr` 版本、安装 Manifest、不可变 revision，以及由 `scripts/freeze_production_assets.py` 生成的 SHA-256 + 文件 stat 清单 | `FROZEN_SHA256_AND_STAT`。普通预检只比较文件 stat，不重复读取全部权重；发布验证使用 `--verify-assets` 重算 SHA-256 |
| RapidOCR | 主 Python 中的 RapidOCR 与 ONNX Runtime、固定 Det/Rec/Cls 权重，各自 SHA-256 和实际 engine 绑定 | `SHA256_VERIFIED` |
| MinerU | checkout 独立 Python、MinerU/Torch/Torchvision、离线选项、冻结的 `mineru.json` 字节快照、revision，以及由 `scripts/freeze_production_assets.py` 生成的 SHA-256 + 文件 stat 清单 | `FROZEN_SHA256_AND_STAT`。普通预检只比较文件 stat；发布验证使用 `--verify-assets` 重算 SHA-256 |

`READY` 表示该级别的身份与文件检查通过。其他状态为 `NOT_READY`、`NOT_INSTALLED`、`MISCONFIGURED`、`IDENTITY_UNVERIFIED`、`CHECK_ERROR`。选择缺少 V1 运行时身份验证器的适配器会使严格预检失败。部署策略如要求所有模型权重字节经过深度证明，应在安装或发布阶段另行校验 Indra 和 MinerU 的文件完整性。

HTTP `/parse` 继续通过默认 Core 构造器解析上传件。其请求无 Profile 路径参数，其进程启动与响应目前没有实现 V1 生产锁定及来源合同。JudgeAI V1 使用独立 Core 子进程。

## JSON 示例

坏路径返回该形状，并以退出码 `2` 结束。

```json
{
  "schema_version": "1.0",
  "status": "CONFIGURATION_FAILED",
  "error": "Invalid provider_profile /srv/pdffast/configs/profiles/missing.json: [Errno 2] No such file or directory"
}
```

当前工作树的完整成功样例为本地验收目录 `outputs/governance_v1_20261120/reviewed/preflight_verified.json`。它使用 `--probe`，三个依赖探测均为 `PASS`。其中 `fingerprint_input` 可直接用于上面的重算示例。

