<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.0.0. Edit the central template, then re-sync. -->
# Playbook: Debugging

1. **Pin the symptom.** Exact error, logs, version, device/OS, and steps. Write them down.
2. **Reproduce.** Make the failure happen on demand, ideally as a failing test or script.
   Cannot reproduce → gather more data; do not guess-fix.
3. **Narrow.** Bisect by input, by code path, or by history (`git bisect` on a local branch).
4. **Explain.** State the root cause in one sentence with `path:line`. If you cannot explain
   why the code fails, you have not found the cause.
5. **Fix minimally.** Change the cause; keep the diff small.
6. **Prove.** Reproduction fails before, passes after. Run the other checks.
7. **Generalise carefully.** Search for the same pattern elsewhere; report it, fix in scope.
8. **Record.** Root cause and evidence go in the PR description.

Device-side issues: never run commands that write to system partitions, flash, or change
kernel parameters on a device without explicit approval and a rollback plan.
