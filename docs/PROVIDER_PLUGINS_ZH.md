# PDFFast V3 Provider 插件接入说明

## 1. 范围与原则

本文描述 V3 在当前生产闭包之外新增 Provider 的最小接入机制，不重构 Stage 1–10、Gate、Router 或 Stage 10 的语义。默认六引擎、冻结路由候选、已有 `CanonicalPrediction` 合同和 JudgeAI 固定版本均不变。

- `ProviderRegistry` 只接受六个内置 Provider，或从可信本地配置**显式注册**的插件；不进行自动发现。
- 每个插件必须声明唯一名称、`kind`、Adapter 的 `factory` 和 Normalizer 的 `normalizer`（格式均为 `模块路径:可调用对象`）。不得覆盖六个内置生产名称。
- `provider_chain_overrides` 是实验/部署时的显式策略开关：不设置就维持原来的固定候选链和默认输出行为。支持按 `capability_route` 或具体 `policy_class` 设置（后者优先）。
- `runtime_enabled=true` 是**可执行**要求，`benchmark_enabled` 不控制生产路由。链上的每个 Provider 仍经完整闭包验证、Preflight 与 Canonical 标准化。
- 每个新 Provider 必须在隔离测试验证运行环境、超时、结果 Schema、失败回退、证据引用及业务质量后才能纳入生产策略。

## 2. 配置范例

在根目录 `configs/providers.json` 的**已有** `providers` 对象中增加新 Provider 配置（不要删掉现有六项），并增加同层字段：

```json
{
  "providers": {
    "minicpm_ocr_local": {
      "kind": "minicpm_ocr_worker",
      "runtime_enabled": true,
      "benchmark_enabled": true,
      "python_executable": "runtimes/minicpm/.venv/bin/python",
      "required_artifacts": []
    }
  },
  "plugins": {
    "minicpm_ocr_local": {
      "kind": "minicpm_ocr_worker",
      "factory": "my_pdffast_plugins.minicpm:MiniCPMOCRProvider",
      "normalizer": "my_pdffast_plugins.minicpm:normalize_minicpm"
    }
  },
  "provider_chain_overrides": {
    "PAGE_DOCUMENT_LAYOUT_PARSE": ["minicpm_ocr_local", "mineru_local", "marker_local"]
  }
}
```

**以上仅为增量结构示意**：实际 JSON 必须保留现有六个 `providers` 成员；工厂与 Normalizer 是需要另行实现的用户模块，配置本身不会下载模型、创建虚拟环境或提供 MiniCPM-OCR 算法。初次验证建议在独立测试环境使用，而不是直接改现有生产候选链。

若仅想注册用于单 Provider Benchmark 而不参与生产，只保留 `plugins` 与 `providers` 条目，不配置 `provider_chain_overrides`；真正执行该 Provider 时仍需要明确允许并打开 `runtime_enabled`。

## 3. Adapter 合同

插件工厂接收 `(name: str, config: dict)`，返回满足 `pdffast.providers.base.Provider` 协议的对象：

```python
class MiniCPMOCRProvider:
    def __init__(self, name: str, config: dict): ...
    def preflight(self) -> ProviderPreflight: ...
    def initialize(self) -> None: ...
    def execute(self, task: ProviderTask) -> RawProviderResult: ...
    def close(self) -> None: ...
```

Adapter 应处理其独立 Worker/SDK 的加载、推理、关闭，输出 `RawProviderResult`。不应从 Provider 内修改 Gate、Router、Stage 10，也不应在返回结果中臆造结构关系。

## 4. Normalizer 合同

插件 Normalizer 必须是可调用对象，接受以下关键字参数：

```python
def normalize_minicpm(*, result, manifest_task, manifest_path, result_path, known_hashes=None) -> dict:
    ...  # 返回满足 CanonicalPrediction 的完整字典
```

返回值必须通过现有 `validate_canonical`：`task_id`、`provider`、`status`、`text`、`tables`、`formulas`、`reading_blocks`、`relations`、`source_artifacts` 等字段必需；`text` 包含 `availability/content/raw_content`，结构通道包含 `availability/items`。可以复用 `pdffast.providers.normalization` 的构造辅助函数。不得把不可靠坐标或平面 OCR 推断成权威语义关系。运行时会先记录 raw JSON 和输入 Manifest，再调用 Normalizer。

## 5. 路由覆盖选择器

`provider_chain_overrides` 支持下面的选择器：

| Capability Route | 可选更具体的 policy_class |
|---|---|
| PAGE_DOCUMENT_OCR | PAGE_FAST_OCR_ESCALATION |
| PAGE_DOCUMENT_LAYOUT_PARSE | PAGE_LAYOUT_PARSE_ESCALATION |
| REGION_MULTIMODAL_PARSE | REGION_TEXT_FIRST / REGION_COMPLEX_GAP_AWARE / REGION_GENERIC_GAP_AWARE |
| INLINE_CONTEXT_PARSE | INLINE_MATH_CONTEXT |

每条链是 1–10 个不重复的 Provider 名称，越靠前越优先。当前策略仍按原有 Acceptance 合同接受或升级；这不是按照模型质量自动排名。覆盖只改变候选顺序，不改变 Stage 8 是否要求增强、区域保留或 Canonical 渲染语义。报告会记录实际覆盖设置。

## 6. 安全与验证

- `plugins` 为本地管理员信任配置，任意 Python 工厂和 Normalizer 都能执行代码；不要接受来自上传 PDF、HTTP 请求或不可信用户的插件路径。
- 修改生产路由前，先运行单 Provider Preflight 和同输入结果标准化测试，再做真实 PDF 的质量、时间、内存与失败回退对比。
- 新增 Provider 的重模型建议独立 Python 环境/Worker，不能假设仅注册就具有跨平台部署能力。
- 该机制不自动把新 Provider 列为已评测的 frontier，也不自动提高 Gate / Audit 的内容准确性。
- 内置六项不启用覆盖时应保持原有契约与结果；JudgeAI 仍须显式更新锁定提交后才使用新版本。
