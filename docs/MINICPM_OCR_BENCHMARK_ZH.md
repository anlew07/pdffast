# MiniCPM-OCR 1.0：第七个 Provider 的本地 Benchmark 指南

> 状态：开发分支中的可选插件，**没有进入默认六 Provider 生产候选链**。本指南不需要 Docker，也不需要修改 JudgeAI。
> 这版仅为官方识别服务的**单图 Text Recognition**，不包含官方 `minicpmvocr` SDK 的整页布局定位/裁剪/阅读顺序重建。不要将它的文字成绩称为完整文档结构解析成绩。

## 0. 工作区与测试前提

现有开发工作区：`/Users/admin/Workspace/pdffast-provider-benchmark`。已经准备好的 27 页视觉输入：`/Users/admin/Downloads/pdffast_benchmark_27_ready/manifest.jsonl`。

```bash
cd /Users/admin/Workspace/pdffast-provider-benchmark
git pull --ff-only
uv run --frozen pytest -q tests/unit/test_minicpm_ocr_plugin.py \
  tests/unit/test_provider_plugins.py tests/unit/test_provider_benchmark.py
```

## 1. 检查本机工具

先在一个新终端执行：

```bash
command -v cmake || true
command -v git
command -v llama-server || true
uname -m
```

若没有 `cmake`，macOS 可通过 `brew install cmake` 安装。若本机已有**兼容 MiniCPM-OCR 1.0** 的 `llama-server`，可以直接复用，不要重复编译。模型和权重不放进 pdffast 的 Git 仓库。

如需重新编译，官方验证参考版本为 `llama.cpp b11901`（Apple Silicon 默认使用 Metal）：

```bash
mkdir -p /Users/admin/Workspace/minicpm-ocr-runtime
cd /Users/admin/Workspace/minicpm-ocr-runtime
git clone --branch b11901 --depth 1 https://github.com/ggml-org/llama.cpp.git
cmake -S llama.cpp -B llama.cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build llama.cpp/build -j 4 --target llama-server
```

官方参考：[MiniCPM-OCR llama.cpp 部署指南](https://github.com/OpenBMB/MiniCPM-OCR/blob/main/docs/llamacpp_deploy.md)。

## 2. 准备模型（仅需要准备一次）

初次验证建议 Q8_0 主模型（约 0.81 GB）和 **必需**的 F16 vision projector（约 0.90 GB），先**不启用 DSpark 草稿头**，减少环境变量。Q4/K_M 可在后续单独建 Profile 对比，但不能默认当作同一个模型运行记录。

```bash
mkdir -p /Users/admin/Models/minicpm-ocr-1.0
cd /Users/admin/Models/minicpm-ocr-1.0

curl -fL --retry 3 \
  -o MiniCPM-OCR-1_0-Q8_0.gguf \
  https://huggingface.co/openbmb/MiniCPM-OCR-1.0-gguf/resolve/main/MiniCPM-OCR-1_0-Q8_0.gguf

curl -fL --retry 3 \
  -o mmproj-model-f16-4x.gguf \
  https://huggingface.co/openbmb/MiniCPM-OCR-1.0-gguf/resolve/main/mmproj-model-f16-4x.gguf

ls -lh *.gguf
```

下载文件若存在，应优先核验后复用。官方模型卡：[GGUF 权重](https://huggingface.co/openbmb/MiniCPM-OCR-1.0-gguf)。模型许可证：Apache-2.0（仍应保留版权与许可证要求）。

## 3. 终端 A：启动本地 MiniCPM 推理服务

```bash
/Users/admin/Workspace/minicpm-ocr-runtime/llama.cpp/build/bin/llama-server \
  --model /Users/admin/Models/minicpm-ocr-1.0/MiniCPM-OCR-1_0-Q8_0.gguf \
  --mmproj /Users/admin/Models/minicpm-ocr-1.0/mmproj-model-f16-4x.gguf \
  --n-gpu-layers 99 \
  --ctx-size 8192 \
  --parallel 1 \
  --host 127.0.0.1 \
  --port 18499 \
  --alias minicpm-ocr \
  --jinja \
  --reasoning off
```

终端 A 保持运行。另开终端检查：

```bash
curl --noproxy 127.0.0.1 -fsS http://127.0.0.1:18499/health
curl --noproxy 127.0.0.1 -fsS http://127.0.0.1:18499/v1/models
```

其中 `/v1/models` 返回的 `data[].id` 必须包含 `minicpm-ocr`。若模型服务没有此 ID，修改配置的 `model`，**不要盲目修改注册名**。当模型上下文满/生成中断时，提高服务上下文长度与 `--max-tokens`，并将截断标记计入失败/告警分析。

## 4. 终端 B：生成 Benchmark 专用配置（不修改生产）

```bash
cd /Users/admin/Workspace/pdffast-provider-benchmark

uv run --frozen python -m tools.provider_benchmark.configure_minicpm \
  --base configs/providers.json \
  --out outputs/provider_benchmark/providers.with_minicpm.json \
  --base-url http://127.0.0.1:18499/v1 \
  --model minicpm-ocr \
  --model-variant Q8_0 \
  --backend-revision b11901
```

新增 `minicpm_ocr_local` 只存在于这份**临时 JSON** 中：
- `benchmark_enabled=true`
- `runtime_enabled=false`
- Adapter 为 `pdffast.providers.minicpm_ocr:MiniCPMOCRProvider`
- Normalizer 为 `pdffast.providers.minicpm_normalizer:normalize`
- 不变更原有六 Provider 的候选链

## 5. 先跑 3 页，再扩展到 27 页

若 `smoke_3.jsonl` 尚不存在：

```bash
head -n 3 /Users/admin/Downloads/pdffast_benchmark_27_ready/manifest.jsonl \
  > /Users/admin/Downloads/pdffast_benchmark_27_ready/smoke_3.jsonl
```

Dry-run（不连接服务、不加载模型）：

```bash
uv run --frozen python -m tools.provider_benchmark.run \
  --manifest /Users/admin/Downloads/pdffast_benchmark_27_ready/smoke_3.jsonl \
  --provider-config outputs/provider_benchmark/providers.with_minicpm.json \
  --providers minicpm_ocr_local \
  --out outputs/provider_benchmark/minicpm_smoke_001 \
  --dry-run
```

启动服务后，去掉 `--dry-run`，并使用**另一个输出目录**：

```bash
uv run --frozen python -m tools.provider_benchmark.run \
  --manifest /Users/admin/Downloads/pdffast_benchmark_27_ready/smoke_3.jsonl \
  --provider-config outputs/provider_benchmark/providers.with_minicpm.json \
  --providers minicpm_ocr_local \
  --out outputs/provider_benchmark/minicpm_smoke_real_001
```

`predictions.jsonl` 和 `run_manifest.json` 的指标与六个老 Provider 一样。若 3 页全部成功，再将 `--manifest` 指向 27 页 `manifest.jsonl`，将 `--out` 换成 `outputs/provider_benchmark/minicpm_27_v1`。

注意：直接识别**整页**并使用 `Text Recognition:`，对表格、公式和复杂版面并不是 MiniCPM-OCR 官方完整 SDK 的最优用法。这轮主要验证**第七个 Provider 的直接识别能力和运行成本**；要比较完整布局解析能力，后续应再接 SDK 或先分块、按文字/表格/公式选 Prompt，并独立计入分块和布局成本。

## 6. Jev 单独测，不要当成第八个 OCR Provider

MiniCPM-OCR Jev 是另一款**质量判别模型**，不能输出 OCR 文本。官方有两种不同评分服务：

- `/v1/score`：要求原图 + 候选重新渲染图片 + 候选文本（不能直接传原图和文本）。
- `/v1/rm/score_best`：官方 render+score 服务，可在内部渲染，比较同一块区域的多个候选。

Jev 的 `prob_1` 是一致性判别概率，不是字符正确率或 CER。先完成七个解析 Provider 的独立运行，再用**同一原始区域和候选结果**评测 Jev 与人工标签的一致性。Jev 不得直接参与生产 Quality Gate，也不自动修改路由。

官方：[Jev llama.cpp SDK 部署与请求协议](https://github.com/OpenBMB/MiniCPM-OCR/blob/main/docs/llamacpp_deploy_jev_en.md)。

## 7. 验收边界

- 本代码属于 Draft PR，尚未在用户本机加载 MiniCPM GGUF 完成实测。
- 单元测试使用假服务响应验证 Adapter 和标准化合同；不代表真实模型精度。
- 测试素材不上传 GitHub，外部服务默认仅允许本地地址；远端推理涉及业务文档，需要另行审核。
- 其他六个 Provider 的基准和生产策略保持不变。
