"""Application service for one PDFFast parse request."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path

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
    ParseExecutionError,
    ProductionPreflightError,
)
from pdffast.pipeline.artifacts import ArtifactPaths
from pdffast.pipeline.context import PipelineContext
from pdffast.pipeline.runner import run_core_pipeline
from pdffast.providers.registry import ProviderRegistry
from pdffast.providers.runtime_normalization import normalize_runtime_result
from pdffast.result import ParseResult
from pdffast.runtime import observe_parse


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

    def parse(
        self,
        pdf_path: Path,
        *,
        run_id: str = "parse",
        case_id: str | None = None,
        expected_input_sha256: str | None = None,
        execution_request: dict | None = None,
    ) -> ParseResult:
        _validate_run_id(run_id)
        if expected_input_sha256 is not None and (
            not isinstance(expected_input_sha256, str)
            or len(expected_input_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_input_sha256)
        ):
            raise ConfigurationError("expected_input_sha256 must be a lowercase SHA-256 digest")
        if execution_request is not None:
            if self.config.provider_profile is None:
                raise ConfigurationError("versioned execution requests require a locked Production Profile")
            if (
                execution_request.get("input_sha256") != expected_input_sha256
                or execution_request.get("schema_version") != "pdffast.execution.request.v1"
            ):
                raise ConfigurationError("normalized execution request does not match parse arguments")
            effective_options = {
                "page_dpi": self.config.page_dpi,
                "region_dpi": self.config.region_dpi,
                "rapidocr_workers": self.config.rapidocr_workers,
                "table_mode": self.config.table_mode,
            }
            if execution_request.get("options") != effective_options:
                raise ConfigurationError("execution request options differ from effective parser configuration")
        # Resolve output_root once and pass this exact path through reservation
        # and PipelineContext construction. In particular, Path.resolve() alone
        # does not expand a leading "~".
        output_root = Path(self.config.output_root).expanduser().resolve()
        if self.config.provider_profile is not None:
            return self._parse_locked(
                pdf_path,
                run_id=run_id,
                case_id=case_id,
                output_root=output_root,
                expected_input_sha256=expected_input_sha256,
                execution_request=execution_request,
            )
        if execution_request is not None:
            raise ConfigurationError("execution_request requires a locked Production Profile")
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
            if expected_input_sha256 is not None and metadata.get("sha256") != expected_input_sha256:
                raise InputIdentityMismatchError(expected_input_sha256, metadata.get("sha256"))
            paths.result.manifest_json.parent.mkdir(parents=True, exist_ok=True)
            paths.result.manifest_json.write_text(
                json.dumps({"run_id": run_id, "input": metadata}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return self._parse(
                pdf_path, run_id=run_id, case_id=case_id, input_metadata=metadata,
                output_root=output_root,
            )

    def _parse_locked(
        self,
        pdf_path: Path,
        *,
        run_id: str,
        case_id: str | None,
        output_root: Path,
        expected_input_sha256: str | None = None,
        execution_request: dict | None = None,
    ) -> ParseResult:
        snapshot = load_production_profile(self.config)
        run_dir = output_root / run_id
        if run_dir.exists() or run_dir.is_symlink():
            raise ConfigurationError(f"locked run directory already exists: {run_id}")

        # Bind the caller's expected digest before expensive production preflight
        # and before reserving a run directory. B06-B will replace this path read
        # with a private immutable input snapshot.
        metadata = _fingerprint(Path(pdf_path))
        if metadata.get("status") != "COMPLETE":
            raise ParseExecutionError(
                "Unable to fingerprint locked parse input",
                run_dir=run_dir,
                stage="input_validation",
                details={"fingerprint_status": metadata.get("status"), "input_error": metadata.get("error")},
            )
        if expected_input_sha256 is not None and metadata.get("sha256") != expected_input_sha256:
            error = InputIdentityMismatchError(expected_input_sha256, metadata.get("sha256"))
            error.run_id = run_id
            raise error

        report = preflight_snapshot(snapshot, self.config)
        if report["status"] != "PASS":
            error = ProductionPreflightError(report)
            error.run_id = run_id
            raise error
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        marker = _locked_run_marker(run_dir)
        try:
            marker.touch(exist_ok=False)
        except FileExistsError as exc:
            raise ConfigurationError(f"locked run directory already reserved: {run_id}") from exc
        try:
            run_dir.mkdir(exist_ok=False)
        except OSError as exc:
            marker.unlink()
            raise ConfigurationError(f"cannot reserve locked run directory: {run_id}") from exc
        return self._parse(
            pdf_path,
            run_id=run_id,
            case_id=case_id,
            input_metadata=metadata,
            output_root=output_root,
            locked=snapshot,
            production_identity=report,
            execution_request=execution_request,
        )

    def _parse(
        self,
        pdf_path: Path,
        *,
        run_id: str,
        case_id: str | None,
        input_metadata: dict,
        output_root: Path,
        locked: ProductionProfile | None = None,
        production_identity: dict | None = None,
        execution_request: dict | None = None,
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
