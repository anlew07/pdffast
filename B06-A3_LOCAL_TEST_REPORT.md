# B06-A3 本地自动化测试与合同闭环

## 验收结果

合同闭环用例通过。默认离线全集 **673 通过、1 个已复现的基线失败、19 跳过、61 未选中**。A3 的全部执行均在本地。

| 范围 | 验证 |
| --- | --- |
| Request 与 Schema | 同一参数矩阵覆盖版本、缺项、未知字段、非法 run_id、非法 SHA、Provider 与 Profile 参数、空 options。 |
| ParseService 与身份 | 版本化与旧入口通过同一 Native Core。非法请求、空或不可读文件和摘要不符在预检及输出预留前中止。 |
| Success 与 Partial | Native 回执通过 Success Schema。有可用正文的终态保留走实际 Provider Executor、Canonical、Renderer 和 Audit，返回 `PARTIAL_SUCCESS`。只有占位符时拒绝交付。 |
| Error 与诊断 | CLI 与 Python 覆盖请求、预检、初始化、Provider 执行、审计、取消。验证稳定错误码、run_id、错误 Schema、脱敏证据和退出码。 |
| PDF、Manifest 与 Artifact | PDF 实际摘要与请求、结果合同及根 Manifest 一致。正例逐项重算 Markdown、Canonical、Audit、Production Manifest、策略、索引和任务证据的摘要。对每个必需产物分别篡改均触发独立验签拒绝。 |
| 路径 | 相对路径越界、产物链接及链接父目录被拒绝。摘要校验和语义解析使用同一字节快照。 |
| 兼容 | 原有 `parse()`、CLI 人读模式和 Native Core 用例继续运行。直接脚本从所属 worktree 导入，模块模式和直接路径模式均已验证。 |

## 运行记录

- Python 3.12.13，使用已有项目虚拟环境与本机缓存的开发依赖。执行 `python -m compileall -q pdffast scripts`，pycache 定向到系统临时目录。
- Request、Success 和 Error Schema 均通过 Draft 2020-12 检查。差异和暂存区检查通过。
- 默认命令为 `python -m pytest -q -p no:cacheprovider --tb=short`。
- 首次默认回归发现直接运行 `scripts/run_pipeline.py` 时共享虚拟环境会导入主工作区旧包。修复脚本所属 worktree 的导入并加入直接调用验证后，CLI 与 Canonical 回归 **17 项通过**，全量重跑该问题消失。
- 当前唯一失败为 `test_mineru_disables_ort_telemetry_before_either_child_starts`，错误为 `locked MinerU requires the preflight tools-config snapshot`。使用原始 HEAD 离线归档复现同一异常。
- 原始 HEAD 归档运行有 625 通过、19 跳过、61 未选中。归档中的另一个失败是依赖真实 Git 仓库的生产 CLI 冻结身份测试，归档没有 Git 元数据；该用例在实际 worktree 默认套件通过。
- 19 项跳过均为需要显式授权启动临时 launchd Job 的部署恢复测试。61 项由默认 marker 排除，分别属于 `migration`、`regression`、`provider`，涉及历史迁移、完整业务回归与实 Provider 环境。A5 仅针对最小真实 PDF 验收。

## 差异范围

Provider Registry、Provider 实现、路由、Quality Gate 和 GitHub Actions 保持原样。Fallback Executor 的一处改动只为 Observer 提供关联任务 ID，未改变候选顺序、回退规则或任务执行。测试临时文件和字节码位于系统临时目录。

## A4 整改后复跑

复审整改补充了 RapidOCR 公开身份投影、Renderer 门禁、占位符与纯机器码抑制说明、合法标题与已验证解码、Python run_id 和多 Provider 清理归因测试。重点用例 102 项通过，默认离线全集复跑 673 项通过，唯一失败与原始基线一致。

## 合并前复核

为锁定 MinerU 测试补齐合成 tools-config 快照，保留原有探测及 Worker 遥测断言。默认离线全集复跑为 **674 通过、0 失败、19 跳过、61 未选中**。
