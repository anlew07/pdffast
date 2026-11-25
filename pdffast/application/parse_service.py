"""Application service for one PDFFast parse request."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Any

from pdffast.application.execution_contract import validate_execution_request
from pdffast.application.input_fingerprint import fingerprint_input as _fingerprint
from pdffast.application.production_preflight import preflight_snapshot
from pdffast.application.production_profile import (
    ProductionProfile,
    load_production_profile,
)
from pdffast.config import ParserConfig
from pdffast.errors import (
    ConfigurationError,
    InputIdentityMismatchError,
    InputUnavailableError,
    PDFFastError,
    ParseCancelledError,
    ParseExecutionError,
    ProductionPreflightError,
    RunReservationError,
)
from pdffast.pipeline.artifacts import ArtifactPaths
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_core_pipeline
from pdffast.providers.registry import ProviderRegistry
from pdffast.providers.runtime_normalization import normalize_runtime_result
from pdffast.result import ParseResult
from pdffast.runtime import check_parse_cancelled, observe_parse


def _validate_run_id(run_id: str) -> None:
    if (
        not isinstance(run_id, str)
        or not run_id
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
        or "\x00" in run_id
    ):
        raise ConfigurationError("run_id must be a single safe directory name")


def _locked_run_marker(run_dir: Path) -> Path:
    return run_dir.parent / f".{run_dir.name}.pdffast-locked"


@dataclass
class ParseService:
    config: ParserConfig

    def parse(self, pdf_path: Path, *, run_id: str = "parse", case_id: str | None = None) -> ParseResult:
        _validate_run_id(run_id)
        # Resolve output_root once and pass this exact path through reservation
        # and PipelineContext construction. In particular, Path.resolve() alone
        # does not expand a leading "~".
        output_root = Path(self.config.output_root).expanduser().resolve()
        if self.config.provider_profile is not None:
            return self._parse_locked(
                pdf_path, run_id=run_id, case_id=case_id, output_root=output_root,
            )
        run_path = output_root / run_id
        if run_path.is_symlink():
            raise ConfigurationError(f"run directory cannot be a symlink: {run_id}")
        run_dir = run_path.resolve()
        if run_dir.parent != output_root:
            raise ConfigurationError(f"run directory escapes output root: {run_id}")
        run_dir.mkdir(parents=True, exist_ok=True)
        marker = _locked_run_marker(run_dir)
        if marker.exists() or marker.is_symlink():
            raise ConfigurationError(f"cannot reuse a locked run directory: {run_id}")
        paths = ArtifactPaths.for_run(run_dir)
        with observe_parse(
            run_id,
            log_path=paths.diagnostics.pipeline_log if self.config.capture_output else None,
        ):
            metadata = _fingerprint(Path(pdf_path))
            paths.result.manifest_json.parent.mkdir(parents=True, exist_ok=True)
            paths.result.manifest_json.write_text(
                json.dumps({"run_id": run_id, "input": metadata}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return self._parse(
                pdf_path, run_id=run_id, case_id=case_id, input_metadata=metadata,
                output_root=output_root,
            )

    def parse_request(
        self, pdf_path: Path, request: Mapping[str, Any], *, case_id: str | None = None,
    ) -> ParseResult:
        run_id = request.get("run_id") if isinstance(request, Mapping) else None
        try:
            normalized = validate_execution_request(request)
            if self.config.provider_profile is None:
                raise ConfigurationError("versioned execution requests require a locked Production Profile")
            check_parse_cancelled()
            try:
                output_root = Path(self.config.output_root).expanduser().resolve()
            except (OSError, RuntimeError) as exc:
                raise RunReservationError("cannot resolve the run output root") from exc
            return self._parse_locked(
                pdf_path,
                run_id=normalized["run_id"],
                case_id=case_id,
                output_root=output_root,
                execution_request=normalized,
            )
        except (PDFFastError, ParseCancelledError) as exc:
            exc.run_id = run_id
            raise

    def _parse_locked(
        self,
        pdf_path: Path,
        *,
        run_id: str,
        case_id: str | None,
        output_root: Path,
        execution_request: dict[str, Any] | None = None,
    ) -> ParseResult:
        metadata = None
        if execution_request is not None:
            source = Path(pdf_path)
            try:
                is_file = source.is_file()
            except OSError:
                is_file = False
            if not is_file:
                raise InputUnavailableError({"fingerprint_status": "FAILED", "byte_size": None})
            metadata = _fingerprint(source)
            if metadata["status"] != "COMPLETE" or not metadata.get("byte_size"):
                raise InputUnavailableError({
                    "fingerprint_status": metadata["status"],
                    "byte_size": metadata.get("byte_size"),
                })
            expected = execution_request["input"]["sha256"]
            if metadata["sha256"] != expected:
                raise InputIdentityMismatchError(expected, metadata["sha256"])

        try:
            snapshot = load_production_profile(self.config)
        except ConfigurationError as exc:
            exc.stage = "production_preflight"
            raise
        run_dir = output_root / run_id
        if run_dir.exists() or run_dir.is_symlink():
            raise RunReservationError(f"locked run directory already exists: {run_id}")
        report = preflight_snapshot(snapshot, self.config)
        if report["status"] != "PASS":
            raise ProductionPreflightError(report)
        check_parse_cancelled()
        marker = _locked_run_marker(run_dir)
        try:
            run_dir.parent.mkdir(parents=True, exist_ok=True)
            marker.touch(exist_ok=False)
        except FileExistsError as exc:
            raise RunReservationError(f"locked run directory already reserved: {run_id}") from exc
        except OSError as exc:
            raise RunReservationError(f"cannot reserve locked run directory: {run_id}") from exc
        try:
            run_dir.mkdir(exist_ok=False)
        except OSError as exc:
            try:
                marker.unlink(missing_ok=True)
            except OSError as cleanup:
                exc.add_note(f"Reservation marker cleanup failed: {type(cleanup).__name__}")
            raise RunReservationError(f"cannot reserve locked run directory: {run_id}") from exc
        if metadata is None:
            metadata = _fingerprint(Path(pdf_path))
            if metadata["status"] != "COMPLETE":
                raise ParseExecutionError("Unable to fingerprint locked parse input", run_dir=run_dir)
        return self._parse(
            pdf_path, run_id=run_id, case_id=case_id, input_metadata=metadata,
            output_root=output_root, locked=snapshot, production_identity=report,
            execution_request=execution_request,
        )

    def _parse(
        self, pdf_path: Path, *, run_id: str, case_id: str | None, input_metadata: dict,
        output_root: Path, locked: ProductionProfile | None = None,
        production_identity: dict | None = None, execution_request: dict[str, Any] | None = None,
    ) -> ParseResult:
        config = self.config
        if config.provider_profile is not None and locked is None:
            raise ConfigurationError("provider_profile requires a verified locked snapshot")
        project_root = Path(config.project_root or Path(__file__).resolve().parents[2])
        bundled_configs = None
        if config.project_root is None:
            from importlib.resources import files

            bundled_configs = files("pdffast.resources.configs")
        provider_configs = config.provider_configs
        registry = config.registry
        normalizer = config.normalizer
        provider_chain_overrides = config.provider_chain_overrides
        if locked is not None:
            project_root = locked.root
            provider_configs = locked.configs
            registry = locked.registry
            normalizer = partial(normalize_runtime_result, plugin_normalizer_paths=registry.plugin_normalizers)
            provider_chain_overrides = locked.chains
        elif provider_configs is None or registry is None or normalizer is None:
            try:
                if config.project_root is not None:
                    config_path = project_root / "configs/providers.json"
                    payload = json.loads(config_path.read_text(encoding="utf-8"))
                else:
                    payload = json.loads(
                        bundled_configs
                        .joinpath("providers.json")
                        .read_text(encoding="utf-8")
                    )
                if provider_configs is None:
                    provider_configs = payload["providers"]
                if registry is None:
                    plugins = config.provider_plugins if config.provider_plugins is not None else payload.get("plugins", {})
                    registry = ProviderRegistry(base_dir=project_root, plugins=plugins)
                if normalizer is None:
                    paths = registry.plugin_normalizers if isinstance(registry, ProviderRegistry) else {}
                    normalizer = partial(normalize_runtime_result, plugin_normalizer_paths=paths)
                if provider_chain_overrides is None:
                    provider_chain_overrides = payload.get("provider_chain_overrides")
            except (OSError, KeyError, TypeError, ValueError) as exc:
                location = str(config_path) if config.project_root is not None else "PDFFast 内置资源 providers.json"
                raise ConfigurationError(f"无法加载 Provider 配置：{location}: {exc}") from exc
        context = PipelineContext.create(
            project_root=config.project_root or project_root,
            pdf=Path(pdf_path),
            output_root=output_root,
            run_id=run_id,
            case_id=case_id,
            page_dpi=config.page_dpi,
            region_dpi=config.region_dpi,
            rapidocr_workers=config.rapidocr_workers,
            table_mode=config.table_mode,
            output_mode=config.output_mode,
            capture_output=config.capture_output,
            providers_path=(
                None
                if bundled_configs is None
                else Path(str(bundled_configs.joinpath("providers.json")))
            ),
            route_candidates_path=(
                None
                if bundled_configs is None
                else Path(
                    str(
                        bundled_configs.joinpath(
                            "frozen/stage9_route_candidates_prod_v001.json"
                        )
                    )
                )
            ),
        )
        context = replace(
            context,
            input_metadata=input_metadata,
            defer_result_manifest=locked is not None,
            execution_request=execution_request,
        )
        return run_core_pipeline(
            context,
            provider_configs=provider_configs,
            registry=registry,
            normalizer=normalizer,
            provider_chain_overrides=provider_chain_overrides,
            execute_providers=True,
            locked_profile=locked,
            production_identity=production_identity,
        )
