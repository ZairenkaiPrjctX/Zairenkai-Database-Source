<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# Policy: Testing

Canonical standard: `.github/agent-foundation/standards/testing-and-verification.md`.

- [ ] Use only the test/lint commands listed in `CLAUDE.md`. If none: report "Not Configured".
- [ ] Reproduce a bug before fixing it when possible.
- [ ] Add or update tests for changed behaviour when a framework exists.
- [ ] Never skip, disable, or weaken a test or check to get green.
- [ ] Report three things separately: **configured**, **executed**, **passing**.
- [ ] Hardware/root/kernel behaviour not run on a device is reported "unverified on hardware".
- [ ] After changing foundation files, run `validate_agent_setup.py` and fix all errors.
