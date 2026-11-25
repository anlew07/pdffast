# PDFFast V1 合并前 Ruff 核对

Ruff 0.16.4 使用仓库现有规则。初扫范围是相对 `HEAD` 已修改及尚未跟踪的 33 个 Python 文件。基线取 `63eeff3721b9b3de2acdc4de7df75bc9e61477f6` 的同名文件。使用 `git show HEAD:<path>` 取得基线源码，分别将其送入同版本 Ruff 的 `--stdin-filename <path> -`，再按诊断的规则、消息及 Git 差异对应的语句或诊断范围比对。四处 `EXE001` 另以 Git 文件模式 `100644` 核对。

| 分类 | 初扫 | 处理 |
| --- | ---: | --- |
| 旧基线 | 42 | 对应的源码和诊断保留 |
| 本次触发 | 8 | 已修复。修改涉及同一导入块、公开导出列表，或同一个异常处理语句 |
| 本次新增 | 22 | 已修复。基线缺少对应诊断 |
| 合计 | 72 | 初扫范围 |

表中数字为**修复前**工作区的位置，箭头后的数字为 HEAD 对应位置。未列入表的文件在本轮初扫没有诊断。

| 文件 | 旧基线 | 本次触发 | 本次新增 |
| --- | --- | --- | --- |
| `pdffast/__init__.py` | — | `I001` 4 → 4<br>`RUF022` 13 → 9 | — |
| `pdffast/application/parse_service.py` | — | `I001` 3 → 3 | — |
| `pdffast/application/production_preflight.py` | — | — | `PLR0402` 5 |
| `pdffast/application/production_profile.py` | — | — | `I001` 3<br>`TRY004` 84 |
| `pdffast/deployment_recovery.py` | — | — | `FURB167` 187<br>`FURB167` 208 |
| `pdffast/fallback/executor.py` | `UP035` 9 → 8<br>`F401` 11 → 10<br>`TRY004` 99 → 96<br>`BLE001` 209 → 195<br>`G201` 275 → 261<br>`TRY004` 389 → 375 | `I001` 1 → 1 | — |
| `pdffast/fallback/policy.py` | `EXE001` 1 → 1<br>`UP009` 2 → 2<br>`TRY004` 84 → 84<br>`TRY004` 109 → 109<br>`TRY004` 157 → 157<br>`TRY004` 664 → 664 | — | — |
| `pdffast/pipeline/context.py` | `I001` 3 → 3<br>`UP037` 50 → 49 | — | — |
| `pdffast/pipeline/runner.py` | — | `I001` 8 → 8 | — |
| `pdffast/process_supervisor.py` | — | — | `I001` 3 |
| `pdffast/providers/profiles.py` | `UP035` 12 → 12 | — | — |
| `pdffast/providers/rapidocr.py` | `I001` 1 → 1<br>`B009` 18 → 18<br>`BLE001` 20 → 20<br>`TRY004` 28 → 28<br>`TRY004` 70 → 65 | — | — |
| `pdffast/providers/registry.py` | — | `I001` 1 → 1 | — |
| `pdffast/providers/workers.py` | `BLE001` 208 → 178<br>`BLE001` 498 → 391 | `TRY004` 273 → 232<br>`BLE001` 653 → 538 | `I001` 1 |
| `pdffast/result.py` | `UP035` 7 → 7<br>`UP037` 24 → 23 | — | — |
| `scripts/run_indra_triple_regression.py` | `EXE001` 1 → 1<br>`UP017` 203 → 203<br>`UP017` 209 → 209<br>`UP017` 261 → 261 | — | — |
| `scripts/run_pipeline.py` | `EXE001` 1 → 1<br>`UP017` 29 → 29 | — | — |
| `scripts/verify_indra_runtime.py` | `EXE001` 1 → 1<br>`I001` 3 → 3<br>`I001` 43 → 43<br>`UP017` 69 → 69 | — | — |
| `scripts/verify_process_supervision.py` | — | — | `B023` 198 |
| `scripts/verify_production_governance.py` | — | — | `I001` 3<br>`F401` 7<br>`BLE001` 121 |
| `tests/contracts/test_frozen_configs.py` | `I001` 1 → 1 | — | — |
| `tests/unit/test_cli_log_output.py` | `F401` 7 → 7 | — | — |
| `tests/unit/test_deployment_recovery.py` | — | — | `F401` 9 |
| `tests/unit/test_parser_provenance.py` | — | — | `I001` 15<br>`I001` 84<br>`I001` 98<br>`I001` 119 |
| `tests/unit/test_process_supervision.py` | — | — | `PLW1510` 16<br>`PLW1510` 23 |
| `tests/unit/test_production_preflight.py` | — | — | `I001` 1<br>`I001` 91<br>`I001` 180<br>`I001` 236 |
| `tests/unit/test_provider_lifecycle.py` | `RUF012` 16 → 16<br>`RUF012` 17 → 17<br>`RUF012` 18 → 18<br>`RUF012` 20 → 20<br>`PLW1510` 457 → 457 | — | — |
| `tests/unit/test_provider_profiles.py` | `I001` 1 → 1 | — | — |

## 修复说明

- 触及的导入块和公开导出列表按 Ruff 排序。只清除本轮引入的未用导入。
- Profile 类型检查失败仍由现有的 `ConfigurationError` 包装。
- 验收脚本使用显式循环变量绑定、显式退出码检查方式和完整正则标志名。子验收进程记录原有的脱敏错误事件后以状态 1 退出。
- Worker 非对象响应沿用原异常类型与清理流程。锁定关闭协议的异常在收割后保留原始原因和实际退出码。
- Ruff 的规则与配置沿用仓库现状。

## 复核

修复后剩余 42 项，按文件、规则、诊断消息和 HEAD 位置逐项复核，全部与上表的旧基线一致。Ruff 因这 42 项退出 1。`git diff --check` 退出 0。

在当前项目根目录使用 Ruff 0.16.4 复跑。命令通过 Git 获取输入文件并关闭 Ruff cache。

```bash
RUFF=/path/to/ruff-0.16.4
(git diff --name-only -z HEAD; git ls-files --others --exclude-standard -z) \
  | .venv/bin/python -B -c 'import os, sys; paths = sorted(set(sys.stdin.buffer.read().split(bytes([0])))); os.execv(sys.argv[1], [sys.argv[1], "check", "--no-cache", *[os.fsdecode(p) for p in paths if p.endswith(b".py")]])' "$RUFF"
```
