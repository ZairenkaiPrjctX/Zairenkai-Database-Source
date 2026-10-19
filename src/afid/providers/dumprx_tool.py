"""DumprX as a tool provider: local firmware in, extracted tree out (see afid.dumprx)."""

from __future__ import annotations

from afid.providers.base import Health
from afid.providers.local import LocalFirmwareProvider


class DumprXProvider(LocalFirmwareProvider):
    """Same capabilities as local import; `afid firmware dump` runs DumprX first."""

    def health_check(self) -> Health:
        from afid.dumprx import DumprX

        cfg = self.config
        runner = DumprX.from_settings(cfg.settings, cfg.limit("max_extracted_bytes"))
        problems = runner.problems()
        checks = [{"check": "dumprx", "result": p} for p in problems] or [
            {"check": "dumprx", "result": f"pinned checkout {runner.commit[:12]} ready, offline"}
        ]
        return Health(self.provider_id, "failed" if problems else "ok", checks)
