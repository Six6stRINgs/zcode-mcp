# Review report contract

Return Markdown with these sections, in this order:

## Summary
One short paragraph describing the reviewed scope and overall risk.

## Findings
For each finding:

- **Severity:** blocker | high | medium | low
- **Location:** `path/to/file:line` or symbol
- **Problem:** what is wrong
- **Impact:** why it matters
- **Evidence:** concrete code path, test result, or reproduction
- **Suggested fix:** a focused remediation, without editing files

Order findings from highest to lowest severity. If there are no supported findings,
write `No findings` and explain the checks that support that conclusion.

## Verification
List commands/tests run and their outcomes.

## Coverage gaps
List files, behaviors, or environments that were not checked.

Do not claim a test passed unless it was actually run. Do not include speculative
findings without labeling them as uncertain and explaining the missing evidence.
