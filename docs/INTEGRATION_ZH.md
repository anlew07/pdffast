# Python 系统接入

## 选择入口

| 场景 | 入口 | 返回值 |
| --- | --- | --- |
| 普通本地 Python | `PDFFastParser.parse(pdf_path, run_id=...)` | `ParseResult` |
| 锁定生产解析和 JudgeAI | `PDFFastParser.parse_request(pdf_path, request)` 或 Embedded CLI | `ParseResult.execution_contract` 或版本化 JSON 回执 |
| 独立 HTTP 服务 | `python -m pdffast.service` 后调用 `POST /parse`，multipart 字段为 `file` | HTTP Schema `1.0`，含 `run_id`、`markdown`、`canonical` 和 `audit` |

HTTP 适配器接收上传文件并转换为本地受控文件，再调用普通 Parser。Core 使用本地路径和 Python 参数，业务调用方通过事先约定的接口消费结果。JudgeAI 的版本化请求、状态与产物验签见 [Embedded 接入合同](integration/JUDGEAI_EMBEDDED_EXECUTION_CONTRACT_V1.md)。

## 建议封装

```python
from pathlib import Path
from uuid import uuid4

from pdffast import PDFFastParser, ParseResult


class PdfParsingTool:
    def __init__(self, project_root: Path, output_root: Path) -> None:
        self._parser = PDFFastParser(
            project_root=project_root,
            output_root=output_root,
            output_mode="minimal",
        )

    def parse(self, pdf_path: Path, business_id: str) -> ParseResult:
        run_id = f"{business_id}_{uuid4().hex}"
        return self._parser.parse(
            pdf_path,
            run_id=run_id,
            case_id=business_id,
        )
```

业务数据库建议保存 `run_id`、`result_manifest` 和最终状态。不要把内部 Stage JSON 结构写成
业务表字段，也不要依赖 Provider 原始输出，因为这些属于内部诊断契约。

## 错误处理

```python
import logging
from pathlib import Path

from pdffast import ParseExecutionError, PDFFastError, PDFFastParser

logger = logging.getLogger(__name__)
parser = PDFFastParser(output_mode="diagnostic")

try:
    result = parser.parse(Path("./document.pdf"), run_id="job_001")
except ParseExecutionError as exc:
    logger.exception(
        "PDF 解析失败：run_dir=%s log_path=%s",
        exc.run_dir,
        exc.log_path,
    )
except PDFFastError:
    logger.exception("PDFFast 配置或运行错误")
```

不要根据中文错误消息做程序分支；应捕获 `ConfigurationError`、`ProviderUnavailableError`、
`ParseExecutionError` 或它们的父类 `PDFFastError`。

## 并发与生命周期

- 每个调用必须使用独立 `run_id`，避免输出相互覆盖；
- 输入文件在执行完成前保持可读且内容不变；
- Indra、MinerU、Marker、Docling 使用 checkout 下的隔离 Worker；
- Executor 负责关闭其创建的 Provider。受管 Job 的取消和恢复见 [部署恢复合同](contracts/deployment_control_v1.md)；
- 模型可使用用户级缓存，解释器由当前 checkout 的 Provider 配置解析。

## 输出契约

稳定文件契约位于 `<output_root>/<run_id>/result/`。推荐向下游传递 `document.json` 或
`document.md`；`audit.json` 用于判断结构边界是否满足要求；`manifest.json` 用于定位本次结果。

若业务需要集中采集诊断日志，使用 `output_mode="diagnostic"` 并读取
`result.artifacts["pipeline_log"]`。不要在业务代码中遍历编号 Stage 目录。
