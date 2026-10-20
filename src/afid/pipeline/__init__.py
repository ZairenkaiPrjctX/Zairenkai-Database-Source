"""Metadata pipeline for AWS CodeBuild: bounded, metadata-only discovery from the sources in
registry/sources.json, validated firmware records, and a run manifest.

It never downloads firmware: discovery and binary acquisition are separate stages, and this
package implements only the first. See docs/AWS_PIPELINE.md.
"""

from __future__ import annotations

# Exit codes of tools/ingest.py, tools/validate.py and tools/publish_manifest.py. They extend
# the afid CLI's codes (afid.errors) so one table documents both.
EXIT_OK = 0
EXIT_CONFIG = 2  # ConfigError: bad registry, schema or arguments
EXIT_VALIDATION = 3  # ValidationError: records or manifest failed validation
EXIT_PROVIDER = 7  # ProviderError: every selected source failed
EXIT_POLICY = 9  # PolicyViolationError: disabled source, URL policy, unsafe output path
EXIT_BUDGET = 13  # ResourceError: run time, request or size budget exhausted
EXIT_PARTIAL = 14  # some sources or records failed; the manifest is still written
