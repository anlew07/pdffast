"""Worker-local display controls; stdout remains the JSONL protocol channel."""

MINERU_LOGGING_CODE = r'''
import os
import sys
_pdffast_log_mode = os.environ.get("PDFFAST_LOG_MODE", "normal").strip().lower()
if _pdffast_log_mode not in {"quiet", "normal", "debug"}:
    raise ValueError("PDFFAST_LOG_MODE must be quiet, normal or debug")
if _pdffast_log_mode != "debug":
    # Must precede tqdm import: its env defaults are captured on import.
    os.environ["TQDM_DISABLE"] = "1"
    try:
        from loguru import logger as _pdffast_model_logger
    except ImportError:
        import logging
        logging.getLogger("pdffast.worker").warning("MinerU Loguru 降噪不可用：未安装 loguru")
    else:
        _pdffast_model_logger.remove()
        _pdffast_model_logger.add(sys.stderr, level="WARNING")
'''
