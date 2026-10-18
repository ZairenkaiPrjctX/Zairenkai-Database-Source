<!-- Managed by ZairenkaiPrjctX/.github agent-foundation v1.1.0. Edit the central template, then re-sync. -->
# Playbook: Feature delivery

1. **Brief.** Capture the request in `AGENT/templates/task-brief.md`: problem, acceptance
   criteria, out of scope. Unclear criteria → ask before coding.
2. **Discover.** Read `AGENT/PROJECT_CONTEXT.md`, the affected code, tests, and callers.
3. **Plan.** Fill `AGENT/templates/implementation-plan.md`. Share it first if the change
   touches public interfaces, root/kernel code, licensing, or more than a few files.
4. **Branch.** Create a topic branch from the up-to-date default branch.
5. **Implement.** Follow `AGENT/prompts/implement-feature.md`, tests first where possible.
6. **Verify.** Run `/test-and-verify`; fill `AGENT/templates/verification-report.md`.
7. **Document.** Update docs and `AGENT/` facts touched by the change.
8. **Ship for review.** Follow `AGENT/prompts/commit-and-pr.md`: signed commits, draft PR.
9. **Respond.** Address review comments; re-run checks after each push.
