---
name: security-review
description: Review a diff, path, or the whole repository for exploitable security issues (injection, privilege, auth and licensing, secrets, CI supply chain) and rank findings. Use before merging security-sensitive changes or on request.
argument-hint: "[diff, path, or 'repo'] [threat context]"
---
<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# /security-review

**When:** a change touches input parsing, root/kernel code, auth, licensing, secrets, or CI;
or a review is requested.
**Input:** `$ARGUMENTS`: target (default: current diff) and who can reach it.

## Procedure
1. Follow `AGENT/prompts/security-review.md`.
2. Keep only findings with a concrete path from attacker-controlled input to impact.

## Restrictions
Read-only. Never open or print secret files; report paths only. Never test exploits against
live systems or devices. Keep the report private.

## Output
Findings ranked critical → low: location, attack path, impact, fix. Then the areas not reviewed.

## Verification
Each finding cites `path:line` you actually read.
