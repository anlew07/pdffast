# Python 系统接入

## 推荐依赖方向

PDFFast Core 接受本地 PDF 路径和普通 Python 参数，返回 `ParseResult`。业务系统、HTTP 层或
任务队列只能依赖这个公共边界，不应让 Core 反向依赖框架类型。

```text
业务编排 / HTTP adapter / 队列 consumer
  -> PDFFastParser.parse(Path)
  -> ParseResult
```

Core 不接收 FastAPI `UploadFile`、HTTP request/response 或 Celery task。未来接入 HTTP 时，
adapter 应先把上传内容保存为受控的本地临时文件，再调用 Parser，最后把 `ParseResult` 映射为
响应。解析 Pipeline 不需要知道传输协议。

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
- 输入文件在 `parse()` 返回前必须保持可读；
- MinerU、Marker、Docling 由 Core 通过隔离 subprocess worker 调用；
- worker 由 executor 在 `finally` 中关闭，业务层不要直接管理 Provider 进程；
- 模型缓存是用户级共享资源，Python 虚拟环境属于当前 V2 工程。

## 输出契约

稳定文件契约位于 `<output_root>/<run_id>/result/`。推荐向下游传递 `document.json` 或
`document.md`；`audit.json` 用于判断结构边界是否满足要求；`manifest.json` 用于定位本次结果。

若业务需要集中采集诊断日志，使用 `output_mode="diagnostic"` 并读取
`result.artifacts["pipeline_log"]`。不要在业务代码中遍历编号 Stage 目录。
