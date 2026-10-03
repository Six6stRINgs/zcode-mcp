---
name: zcode-code-reviewer
description: "Run a read-only code review through a ZCode worker over zcode-mcp, then independently verify the workspace and produce actionable findings. Use when Codex wants ZCode as a review subagent; do not use for implementation edits unless the user explicitly asks for fixes."
---

# ZCode Code Reviewer

Use ZCode as a **read-only review worker** while Codex remains the final reviewer.
The worker may inspect the real project, but it must not modify files during the
review pass.

## Review dispatch

1. Resolve the existing project path. It must already exist.
2. Start a project-level worker with:

```text
zcode_session_new {
  project: "<absolute project path>",
  mode: "plan",
  wait: false,
  text: "<review request and acceptance criteria>"
}
```

3. The review prompt must contain:
   - the review scope: commit, branch, diff, files, or subsystem;
   - the correctness and regression concerns to inspect;
   - explicit read-only constraints: do not edit, delete, stage, commit, or run destructive commands;
   - the required report format from `references/review-report.md`;
   - commands the worker may run for lightweight verification.
4. Observe with `zcode_session_status` and `zcode_session_output`.
5. Collect with `zcode_session_wait`.
6. Call `zcode_session_result` for a machine-readable terminal result.
7. Call `zcode_session_diff` to confirm that the review did not change the workspace.
8. Codex independently reads the diff/files and runs relevant tests before reporting findings.

## Review decisions

- Treat the worker's response as evidence, not as an approval.
- Report findings first, ordered by severity: blocker, high, medium, low.
- Every finding needs a concrete file path, line or symbol when available,
  impact, and a suggested fix. Do not report vague style preferences as bugs.
- If no findings are supported, say so explicitly and list what was checked and
  what was not run.
- Keep review and implementation separate. If the user later requests fixes,
  start a new implementation turn or switch to a separately authorized worker;
  do not silently change the review worker's read-only contract.

## Failure and lifecycle handling

- If the worker times out, use `zcode_session_output` and `zcode_session_status`
  before deciding whether to wait again or stop it.
- If it asks for permission, inspect `zcode_session_permissions`; deny anything
  outside the read-only review scope.
- If it fails, preserve the error and do not convert a partial review into an
  approval.
- Archive a useful long-lived review conversation with `zcode_session_archive`.
  Discard temporary review sessions only when their report is no longer needed.

## Recommended prompt shape

```text
Review <scope> in <project path>.

Read-only contract:
- Do not edit, delete, stage, commit, or reset files.
- Do not change project configuration.

Check:
- correctness and edge cases
- regressions and compatibility
- error handling and resource/lifecycle issues
- tests and missing coverage

Return only a review report following references/review-report.md.
Include exact file paths and line numbers where possible.
```

## Verification checklist

```text
zcode_session_status       → worker state
zcode_session_output       → partial/final text
zcode_session_wait         → terminal reply
zcode_session_result       → structured result
zcode_session_diff         → confirm no workspace mutation
independent tests/diff     → Codex final verification
```
