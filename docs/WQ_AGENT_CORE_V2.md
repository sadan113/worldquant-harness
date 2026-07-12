# WQ Agent Core v2

## Purpose

`worldquant_harness.wq_agent_core` is the canonical execution and memory boundary for WQ research runs. It separates platform side effects from lifecycle state, makes interrupted runs recoverable, and projects structured memory from append-only evidence.

The database is the source of truth. JSONL remains a human-readable compatibility export and an offline import format.

## Identity And Scope

A candidate is identified by normalized expression plus effective simulation settings. The settings include account, region, universe, delay, decay, neutralization, truncation, maxTrade, and maxPosition.

Every event and memory item is isolated by:

- owner (`local` or a valid user UUID)
- account
- region
- universe
- delay

An attempt identity is deterministic from `run_id + candidate_uid + attempt_no`. Replaying the same event does not increase projection revisions or memory support counts.

## Event Lifecycle

The core records these transitions:

```text
candidate_created
  -> validation_passed | validation_rejected
  -> simulation_started
  -> simulation_succeeded | simulation_failed
  -> check_started
  -> check_succeeded | check_blocked
  -> ready | submit_started
  -> submit_succeeded | submission_pending | submit_failed
  -> active_confirmed
```

The database tables are:

| Table | Role |
|:--|:--|
| `wq_agent_events` | Append-only lifecycle evidence |
| `wq_candidate_states` | Current scoped candidate projection |
| `wq_memory_items` | Evidence-ranked positive and negative memory projection |

## Recovery Rules

- Validation failure, simulation failure, and deterministic gate failure are terminal for one attempt. A changed candidate or explicit new attempt is required.
- Correlation pending/missing and check transport errors can be checked again.
- A previous `submit_started` or `submission_pending` is always reconciled with platform status before another POST.
- `ACTIVE` ends the attempt without another submit.
- A retry is allowed only when platform status is explicitly `UNSUBMITTED` and the retry budget remains.
- An unknown status fails closed as `SUBMISSION_PENDING`.

Each submit attempt has a separate event key, so retries and their exact outcomes remain auditable.

## Correlation Gate

The canonical gate requires:

- SELF result is explicit `PASS`.
- SELF value is at or below the configured local cutoff.
- PROD `FAIL` or `PENDING` blocks.
- PROD `MISSING` is allowed only when the platform does not report a pending review.
- Platform check failures always block.

The old `--submit-pending` CLI option is retained only for argument compatibility and is ignored by the canonical runner.

## Memory Projection

Memory keeps evidence class, confidence, support count, contradictions, source event IDs, and source artifacts. Evidence priority is:

```text
platform submit > platform check > simulation > local validation > imported artifact > forum/heuristic
```

An ACTIVE platform outcome supersedes active negative memory for the same scoped candidate. `ScopedMemoryRetriever` applies per-failure quotas so a large successful or self-correlation family cannot crowd every other diagnosis out of the model context. Retrieved rows include diagnosis-specific repair advice.

## Compatibility Paths

- `scripts/wq_live_submit_candidates.py` uses `ExecutionEngine` directly and exports `agent_events.jsonl`, `simulation_results.jsonl`, `check_results.jsonl`, and `submit_results.jsonl`.
- A legacy live output passed with `--resume` is imported into the current run identity before execution resumes.
- The role-based workflow defaults to `agent_event_mode=shadow` from its CLI. Its existing artifacts are imported after `_finish` without changing old stage behavior.
- Direct Python construction of `WQAgentWorkflowConfig` defaults event and v2 memory integration to off, preserving tests and embedding compatibility.

## History Backfill

Dry-run is mandatory by default:

```bash
python scripts/wq_agent_backfill.py \
  --report reports/wq_agent_backfill_report.json
```

Review skipped rows, identity conflicts, ACTIVE identity quality, and event counts. Then apply:

```bash
python scripts/wq_agent_backfill.py \
  --apply \
  --report reports/wq_agent_backfill_apply.json
```

The importer performs no platform calls. It content-deduplicates repeated platform snapshots, hydrates missing expression/settings through alpha and candidate indexes, and uses deterministic event IDs. A second apply must report `applied_events: 0`.

Candidate and memory projections can be rebuilt without re-importing artifacts:

```bash
python scripts/wq_agent_backfill.py --rebuild-projections
```

## Autopilot Branches

Autopilot keeps its DFS-with-small-beam policy but now converts branch fractions into integer candidate/simulation caps. Every selected candidate carries:

- `autopilot_branch`
- `autopilot_branch_budget`
- `autopilot_branch_sequence`

Branch state records current and cumulative candidates, simulations, ready outcomes, ACTIVE outcomes, failure counts, budget rejection counts, and status. Repeated diagnosis-linked failures can mark a branch `pruned`; a resumed autopilot run does not allocate budget to a persistently pruned branch.
