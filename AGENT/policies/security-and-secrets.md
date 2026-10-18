<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# Policy: Security and secrets

Canonical standard: `.github/agent-foundation/standards/security-and-secrets.md`.

- [ ] Never read, print, copy, or commit secrets, tokens, passwords, or private keys.
      Refer to them by name only.
- [ ] `.claude/settings.json` blocks reading common secret files. Do not work around it.
- [ ] Found a committed secret? Stop, do not copy it, report the path to a maintainer.
- [ ] Root, kernel, device-tweak, licensing, and auth code: flag for human review and
      describe the rollback path.
- [ ] CI workflows: pin actions to commit SHAs, least-privilege `permissions:`,
      no secret echoing, avoid `pull_request_target` with untrusted code.
- [ ] Report vulnerabilities privately to maintainers, not in public issues.
