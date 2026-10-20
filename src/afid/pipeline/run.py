"""One pipeline run: select sources, discover within limits, validate, deduplicate, write the
run manifest.

Modes:
- dry-run: no network at all. Records come from the synthetic fixture; sources named with
  --source are reported as "planned" with their effective limits, and nothing is requested.
- discover: only sources named with --source, each of which must be enabled in
  registry/sources.json (which requires an approved review). Limits given on the command
  line can only lower the registry's limits, never raise them.

Everything that can fail without the network (registry, output path, disabled sources) is
checked before the first request.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from afid import __version__
from afid.config import Config
from afid.errors import ConfigError, PolicyViolationError, ProviderError, ValidationError
from afid.pipeline import (
    EXIT_BUDGET,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_PROVIDER,
    EXIT_VALIDATION,
)
from afid.pipeline.discovery import Outcome, gitlab_group_branches, synthetic_items
from afid.pipeline.records import TIMESTAMP_FORMAT, build_record, record_problems
from afid.pipeline.registry import (
    REGISTRY_PATH,
    Limits,
    Provider,
    load_fixture,
    load_registry,
    schema_errors,
    validators,
)
from afid.pipeline.urlpolicy import (
    GuardedHttpClient,
    RequestBudgetExceeded,
    TimeBudgetExceeded,
)
from afid.utils import jsonio, log

LOG = log.get("pipeline")
OUTPUT_BASE = "build"
DEFAULT_OUTPUT = "build/pipeline/manifest.json"
MAX_ERRORS_PER_SOURCE = 50

HttpFactory = Callable[[Provider, Limits, float], GuardedHttpClient]


@dataclass
class RunOptions:
    mode: str
    sources: list[str] = field(default_factory=list)
    output: str = DEFAULT_OUTPUT
    max_pages: int | None = None
    max_records: int | None = None
    max_requests: int | None = None
    timeout: float | None = None
    max_run_seconds: int | None = None
    generated_at: str | None = None


def safe_output_path(root: Path, output: str) -> Path:
    """Resolve the manifest path; it must end in .json and stay inside <root>/build/, after
    symlinks are resolved. Registry, schemas and database files can never be overwritten."""
    candidate = Path(output)
    if candidate.suffix != ".json":
        raise PolicyViolationError(f"output '{output}' must be a .json file")
    target = (candidate if candidate.is_absolute() else root / candidate).resolve()
    base = (root / OUTPUT_BASE).resolve()
    if not target.is_relative_to(base) or target == base:
        raise PolicyViolationError(f"output '{output}' must be inside {OUTPUT_BASE}/")
    return target


def run_timestamp(explicit: str | None, env: dict[str, str] | None = None) -> str:
    """--generated-at, else SOURCE_DATE_EPOCH (reproducible builds), else now (UTC)."""
    env = dict(os.environ) if env is None else env
    if explicit:
        try:
            datetime.strptime(explicit, TIMESTAMP_FORMAT)
        except ValueError:
            raise ConfigError(f"--generated-at '{explicit}' is not YYYY-MM-DDTHH:MM:SSZ") from None
        return explicit
    epoch = env.get("SOURCE_DATE_EPOCH")
    if epoch:
        if not epoch.isdigit():
            raise ConfigError("SOURCE_DATE_EPOCH must be an integer")
        moment = datetime.fromtimestamp(int(epoch), tz=UTC)
    else:
        moment = datetime.now(UTC)
    return moment.strftime(TIMESTAMP_FORMAT)


def effective_limits(base: Limits, opts: RunOptions) -> Limits:
    """Command-line limits may only lower the registry's."""

    def lower(current: Any, requested: Any) -> Any:
        if requested is None:
            return current
        if requested <= 0:
            raise ConfigError("limits must be positive")
        return min(current, requested)

    return replace(
        base,
        max_pages=lower(base.max_pages, opts.max_pages),
        max_records=lower(base.max_records, opts.max_records),
        max_requests=lower(base.max_requests, opts.max_requests),
        request_timeout_seconds=lower(base.request_timeout_seconds, opts.timeout),
        max_run_seconds=lower(base.max_run_seconds, opts.max_run_seconds),
    )


def default_http(user_agent: str) -> HttpFactory:
    def make(provider: Provider, limits: Limits, deadline: float) -> GuardedHttpClient:
        return GuardedHttpClient(
            allowed_hosts=provider.allowed_hosts,
            timeout=limits.request_timeout_seconds,
            max_retries=limits.max_retries,
            backoff=limits.backoff_seconds,
            min_interval=limits.min_interval_seconds,
            user_agent=user_agent,
            max_body=limits.max_response_bytes,
            max_wait=float(min(60, limits.max_run_seconds)),
            deadline=deadline,
            max_requests=limits.max_requests,
        )

    return make


@dataclass
class SourceReport:
    source_id: str
    enabled: bool
    limits: Limits
    status: str = "ok"
    requests: int = 0
    outcome: Outcome = field(default_factory=Outcome)
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        errors = self.outcome.errors
        if len(errors) > MAX_ERRORS_PER_SOURCE:
            keep = MAX_ERRORS_PER_SOURCE - 1
            errors = [*errors[:keep], f"... {len(errors) - keep} more errors"]
        return {
            "source_id": self.source_id,
            "status": self.status,
            "enabled": self.enabled,
            "requests": self.requests,
            "truncated": self.outcome.truncated,
            "limits": self.limits.as_dict(),
            "errors": [e[:500] for e in errors],
        }


def _discover(provider: Provider, limits: Limits, http: GuardedHttpClient) -> SourceReport:
    report = SourceReport(provider.id, provider.enabled, limits)
    try:
        if provider.strategy != "gitlab_group_branches":
            raise ConfigError(f"{provider.id}: strategy '{provider.strategy}' cannot discover")
        gitlab_group_branches(provider, http, limits.max_pages, limits.max_records, report.outcome)
    except RequestBudgetExceeded as exc:
        report.outcome.truncated = True  # an expected bound, not a failure
        LOG.info("%s: %s", provider.id, exc)
    except TimeBudgetExceeded as exc:
        report.timed_out = True
        report.outcome.errors.append(str(exc))
    except ProviderError as exc:
        report.outcome.errors.append(str(exc))
        if not report.outcome.items:
            report.status = "failed"
    report.requests = http.requests
    if report.status != "failed" and (report.outcome.errors or report.timed_out):
        report.status = "partial"
    return report


def run(
    root: Path,
    opts: RunOptions,
    http_factory: HttpFactory | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any], Path, int]:
    """Execute a run; returns (manifest, manifest path, exit code). Raises AfidError for
    problems found before any request (configuration, policy)."""
    if opts.mode not in ("dry-run", "discover"):
        raise ConfigError(f"unknown mode '{opts.mode}'")
    registry = load_registry(root)
    out_path = safe_output_path(root, opts.output)
    generated_at = run_timestamp(opts.generated_at)
    v = validators(root)

    unknown = sorted(set(opts.sources) - set(registry.providers))
    if unknown:
        raise ConfigError(f"unknown source(s) {unknown}; known: {sorted(registry.providers)}")
    selected = [registry.providers[s] for s in sorted(set(opts.sources))]
    if opts.mode == "discover":
        if not selected:
            raise ConfigError("discover mode needs at least one explicit --source")
        disabled = [p.id for p in selected if not p.enabled]
        if disabled:
            raise PolicyViolationError(
                f"source(s) {disabled} are disabled in {REGISTRY_PATH}; a source is enabled "
                "only by a reviewed change to the registry (approved review required)"
            )

    reports: list[SourceReport] = []
    providers: dict[str, Provider] = {}
    if opts.mode == "dry-run":
        fixture_provider, raw_items = load_fixture(root)
        report = SourceReport(
            fixture_provider.id, fixture_provider.enabled, fixture_provider.limits
        )
        synthetic_items(fixture_provider, raw_items, report.outcome)
        reports.append(report)
        providers[fixture_provider.id] = fixture_provider
        for p in selected:  # planned only: nothing is requested
            reports.append(
                SourceReport(p.id, p.enabled, effective_limits(p.limits, opts), status="planned")
            )
    else:
        make_http = http_factory or default_http(
            str(Config(root).settings.get("network", {}).get("user_agent", "AFID"))
        )
        for p in selected:
            limits = effective_limits(p.limits, opts)
            http = make_http(p, limits, clock() + limits.max_run_seconds)
            LOG.info("%s: discovering (limits %s)", p.id, limits.as_dict())
            reports.append(_discover(p, limits, http))
            providers[p.id] = p

    records: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    summary = {"discovered": 0, "validated": 0, "skipped": 0, "duplicate": 0, "failed": 0}
    for rep in reports:
        summary["skipped"] += rep.outcome.skipped
        for item_id, problem in rep.outcome.malformed:
            summary["discovered"] += 1
            summary["failed"] += 1
            rejected.append(
                {"source_id": rep.source_id, "source_item_id": item_id, "problems": [problem]}
            )
        for item in rep.outcome.items:
            summary["discovered"] += 1
            rec = build_record(providers[rep.source_id], item, generated_at)
            problems = record_problems(rec, providers[rep.source_id], v["firmware-record"])
            if problems:
                summary["failed"] += 1
                rejected.append(
                    {
                        "source_id": rep.source_id,
                        "source_item_id": item.source_item_id[:512],
                        "problems": [p[:500] for p in problems[:20]],
                    }
                )
            elif rec["record_id"] in records:
                summary["duplicate"] += 1
                if records[rec["record_id"]] != rec:
                    LOG.warning("%s: duplicate item with different content", item.source_item_id)
            else:
                records[rec["record_id"]] = rec
    summary["validated"] = len(records)

    active = [r for r in reports if r.status != "planned"]
    failed_sources = [r for r in active if r.status == "failed"]
    if active and len(failed_sources) == len(active):
        status = "failed"
    elif failed_sources or rejected or any(r.status == "partial" for r in reports):
        status = "partial"
    else:
        status = "ok"
    manifest = {
        "schema_version": "1.0",
        "manifest_type": "afid-metadata-pipeline-run",
        "generated_at": generated_at,
        "mode": opts.mode,
        "status": status,
        "tool": {"name": "afid-metadata-pipeline", "version": __version__},
        "registry": {
            "path": REGISTRY_PATH,
            "registry_version": registry.version,
            "sha256": registry.sha256,
        },
        "sources": [r.as_dict() for r in sorted(reports, key=lambda r: r.source_id)],
        "summary": summary,
        "records": [records[k] for k in sorted(records)],
        "rejected": sorted(
            rejected[:500], key=lambda r: (r["source_id"], r["source_item_id"] or "")
        ),
        "binary_downloads": 0,
    }
    problems = schema_errors(v["run-manifest"], manifest)
    if problems:  # a bug, not a data problem: never write an invalid manifest
        raise ValidationError("generated manifest is invalid: " + "; ".join(problems))
    jsonio.write_if_changed(out_path, manifest)

    if status == "failed":
        code = EXIT_PROVIDER
    elif any(r.timed_out for r in reports):
        code = EXIT_BUDGET
    elif rejected:
        code = EXIT_VALIDATION
    elif status == "partial":
        code = EXIT_PARTIAL
    else:
        code = EXIT_OK
    return manifest, out_path, code
