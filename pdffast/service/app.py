"""
PDFFast HTTP Adapter。

注意：

这里属于 service adapter，
不是 PDFFast Core。

职责只有：

HTTP 上传
    ↓
保存为临时 PDF
    ↓
PDFFastParser.parse(Path)
    ↓
把 ParseResult 映射成 HTTP JSON

PDFFast Core 不感知 FastAPI。
"""

from __future__ import annotations

import os
import asyncio
import threading
import logging
import math
from contextlib import asynccontextmanager
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel

from pdffast.runtime import cancellable_parse

from pdffast import (
    PDFFastError,
    PDFFastParser,
    ParseExecutionError,
)


# ============================================================
# Config
# ============================================================

PROJECT_ROOT = Path(
    os.getenv(
        "PDFFAST_PROJECT_ROOT",
        Path.cwd(),
    )
).expanduser().absolute()

OUTPUT_ROOT = Path(
    os.getenv(
        "PDFFAST_OUTPUT_ROOT",
        PROJECT_ROOT / "outputs" / "service",
    )
).expanduser().absolute()


# ============================================================
# Response
# ============================================================


class HealthResponse(BaseModel):
    status: str


class ParseResponse(BaseModel):
    """
    对业务系统公开的稳定 HTTP 契约。

    不暴露 Stage1 / Stage9 等内部实现。
    """

    schema_version: str = "1.0"

    run_id: str

    markdown: str

    canonical: dict

    audit: dict


# ============================================================
# App
# ============================================================

def _cleanup_budget() -> float:
    budget = float(os.environ.get("PDFFAST_SHUTDOWN_CLEANUP_SECONDS", "30"))
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("PDFFAST_SHUTDOWN_CLEANUP_SECONDS must be finite and positive")
    return budget


@asynccontextmanager
async def service_lifespan(application: FastAPI):
    budget = _cleanup_budget()
    try:
        yield
    finally:
        # Uvicorn cancels HTTP tasks after its graceful window, then sends the
        # lifespan shutdown event. Retain ownership until parse cleanup ends.
        active = dict(application.state.parse_operations)
        for cancelled, _ in active.values():
            cancelled.set()
        if active:
            _, pending = await asyncio.wait(active, timeout=budget)
            if pending:
                logging.getLogger(__name__).error(
                    "PDFFast shutdown cleanup incomplete after %ss; run_ids=%s. "
                    "In-process native calls cannot be forcibly stopped safely.",
                    budget, [active[task][1] for task in pending],
                )


app = FastAPI(
    title="PDFFast Service",
    version="0.1.0",
    lifespan=service_lifespan,
)
app.state.parse_operations = {}


# ============================================================
# Parser Factory
# ============================================================


def create_parser() -> PDFFastParser:
    """
    每次请求创建一个 Parser。

    当前先保持生命周期简单。
    """

    return PDFFastParser(
        project_root=PROJECT_ROOT,
        output_root=OUTPUT_ROOT,
        output_mode="minimal",
    )


# ============================================================
# Health
# ============================================================


@app.get(
    "/health",
    response_model=HealthResponse,
)
def health() -> HealthResponse:
    """
    只表示 HTTP Service 已启动。

    当前不代表所有 Provider / 模型均 READY。
    """

    return HealthResponse(
        status="UP"
    )


# ============================================================
# Parse
# ============================================================


def _parse_pdf_sync(
    file: UploadFile,
    run_id: str,
) -> ParseResponse:
    """
    上传 PDF 并执行一次完整 PDFFast 解析。

    JudgeAI 后续只依赖此接口。
    """

    filename = (
        file.filename
        or "document.pdf"
    )

    if not filename.lower().endswith(
        ".pdf"
    ):
        raise HTTPException(
            status_code=400,
            detail="仅支持 PDF 文件",
        )

    # --------------------------------------------------------
    # HTTP UploadFile 不进入 Core。
    #
    # 先保存成普通本地文件。
    # --------------------------------------------------------

    with tempfile.TemporaryDirectory(
        prefix="pdffast_upload_"
    ) as temp_dir:

        pdf_path = (
            Path(temp_dir)
            / "input.pdf"
        )

        try:

            with pdf_path.open(
                "wb"
            ) as output_file:

                shutil.copyfileobj(
                    file.file,
                    output_file,
                )

            if (
                pdf_path.stat().st_size
                <= 0
            ):
                raise HTTPException(
                    status_code=400,
                    detail="PDF 文件为空",
                )

            parser = create_parser()

            result = parser.parse(
                pdf_path,
                run_id=run_id,
                case_id=filename,
            )

            return ParseResponse(
                run_id=run_id,

                markdown=(
                    result.markdown
                ),

                canonical=(
                    result.canonical
                ),

                audit=(
                    result.audit
                ),
            )

        except HTTPException:
            raise

        except ParseExecutionError as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error_type": (
                        "ParseExecutionError"
                    ),
                    "message": str(exc),
                },
            ) from exc

        except PDFFastError as exc:
            raise HTTPException(
                status_code=500,
                detail={
                    "error_type": (
                        type(exc).__name__
                    ),
                    "message": str(exc),
                },
            ) from exc

        finally:
            file.file.close()

@app.post("/parse", response_model=ParseResponse)
async def parse_pdf(file: UploadFile = File(...)) -> ParseResponse:
    """Preserve the synchronous calculation, with scoped shutdown cancellation.

    Uvicorn first grants requests its configured graceful shutdown window.
    Cancellation after that window stops this parse at a safe checkpoint and
    unblocks isolated Worker waits. In-process native calls must return before
    they can observe cancellation; no unsafe Python-thread termination is used.
    """
    cancelled = threading.Event()
    run_id = f"api_{uuid4().hex}"
    with cancellable_parse(cancelled):
        operation = asyncio.create_task(asyncio.to_thread(_parse_pdf_sync, file, run_id))
        active = app.state.parse_operations
        active[operation] = (cancelled, run_id)
        def completed(task):
            active.pop(task, None)
            if not task.cancelled():
                task.exception()  # Observe failures even if the HTTP task was cancelled twice.
        operation.add_done_callback(completed)
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            cancelled.set()
            try:
                await asyncio.shield(operation)
            except BaseException:
                # The interrupted parse logs its own failure and cleans up in
                # finally. The HTTP task must preserve cancellation, not 200.
                pass
            raise
