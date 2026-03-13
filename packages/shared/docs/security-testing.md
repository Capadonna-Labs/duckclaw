# Security Testing Playbook

This project uses Strix for manual, repeatable pentesting focused on source code risks.

## Scope
- Target: repository code (`./`)
- Mode: manual (on-demand)
- Tooling: Strix CLI in non-interactive mode

## Runbook
1. Ensure Docker is running.
2. Export required environment variables:
   - `STRIX_LLM` (for example `openai/gpt-5`)
   - `LLM_API_KEY`
3. Execute one of the standardized runs:
   - `./scripts/pentest_strix.sh quick`
   - `./scripts/pentest_strix.sh deep`
4. Review evidence in:
   - `.security/pentest-logs/`
   - `strix_runs/`

## Severity policy
- `critical`: open remediation issue immediately; block release until validated fix.
- `high`: open remediation issue in the same cycle; require owner and target date.
- `medium`: add to security backlog with prioritization.
- `low`/`info`: track as hardening opportunities.

## Reproduction and validation
1. Confirm the vulnerable file/function and triggering path.
2. Reproduce the finding locally using the reported steps or PoC.
3. Implement fix with minimal blast radius.
4. Re-run the same Strix mode and verify the finding no longer appears.
5. Link old/new reports or logs in the remediation issue.

## Closure checklist
- Finding severity confirmed.
- Reproduction documented.
- Fix merged.
- Re-test completed with no regression for the same finding.
- Follow-up hardening tasks captured (if applicable).
