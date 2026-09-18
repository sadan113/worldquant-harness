# Private Low-Correlation Engine V2

V2 extends the V1 structural low-correlation gate with a community-inspired five-stage research pipeline and pre-simulation MMR diversification.

## Source boundary

The user-requested WorldQuant Support community post is recorded as a provenance source, but the support page may require authenticated access and was not fully retrievable through public web access.

A public companion repository was verified:

- `GRD-Chang/worldquant-skill`
- public skills visible in the repository:
  - `knowledge_base_search`
  - `alpha-research-recorder`
  - `factor_backtest`

The companion repository does not declare a license in the GitHub metadata/root content inspected during this implementation. V2 therefore **does not copy implementation code** from that repository. It distills workflow ideas into new harness-native code.

## Five-stage pipeline

1. **Knowledge Search**
   - Community/forum evidence
   - dataset/field opportunities
   - legal-input constraints
   - active-alpha crowding context
   - every adopted lesson should keep provenance

2. **Research Recorder**
   - session configuration
   - economic hypothesis/rationale
   - each round's inputs, decisions, failures, and outputs
   - emits `skill_pipeline_events.jsonl`

3. **Candidate Designer**
   - gather a larger candidate pool
   - validate expressions/legal inputs
   - structural fingerprinting
   - MMR diversification against ACTIVE/virtual-ACTIVE inventory
   - only then choose the simulation batch

4. **Factor Backtest**
   - validation before simulation
   - community-compatible batch planning
   - optional strict Rule-of-8 mode
   - no automatic submit

5. **Critic / Repair**
   - metric failures
   - SELF/PROD correlation
   - concentration and coverage failures
   - syntax/platform failures
   - settings-only retry is discouraged after structural correlation failure

## What V2 changes in execution

V1 generated candidates and applied a structural presubmit gate.

V2 moves diversity earlier:

```text
large candidate pool
        ↓
expression/legal validation
        ↓
structural fingerprint
        ↓
MMR vs ACTIVE + virtual ACTIVE
        ↓
selected research batch
        ↓
simulation
        ↓
platform checks / PnL / correlation
        ↓
critic + repair memory
        ↓
presubmit
```

This saves simulation budget because obvious structural clones can lose selection priority before they are simulated.

## MMR objective

The selector balances candidate quality and novelty:

```text
MMR score ≈ quality contribution - diversity_lambda × nearest structural similarity
```

Defaults:

- structural hard cutoff: `0.60`
- diversity lambda: `0.45`
- max same source family per selected batch: `2`

These are private research defaults, not official WorldQuant thresholds.

## Rule-of-8 compatibility mode

The public `factor_backtest` skill describes an 8-expression multi-simulation workflow.

This fork currently uses the upstream harness's single-simulation transport. V2 therefore implements **batch planning and discipline**, not a fake native multiSim transport.

Default:

```text
community_strict_rule_of_eight = false
```

To enforce only complete 8-expression batches:

```powershell
python scripts/wq_agent_workflow.py presubmit-sequential `
  --output-dir reports/wq_agent_runs/v2_rule8 `
  --candidate-files <candidate_file.jsonl> `
  --region USA `
  --universe TOP3000 `
  --delay 1 `
  --target-ready 3 `
  --cycle-candidate-count 8 `
  --max-total-simulations 120 `
  --community-batch-size 8 `
  --community-strict-rule-of-eight `
  --private-lowcorr-cutoff 0.60 `
  --private-lowcorr-mmr-lambda 0.45 `
  --max-virtual-field-signature-count 1
```

When strict mode is enabled, an incomplete final batch is deliberately dropped. Ensure the candidate/simulation budget is at least 8.

## Artifacts

Each run can now produce:

- `skill_pipeline_manifest.json`
- `skill_pipeline_events.jsonl`
- `community_batch_plan.json`
- existing `candidate_pool.jsonl`
- existing `simulation_results.jsonl`
- existing `review_queue.jsonl`
- existing `repair_queue.jsonl`

## Recommended use

For production research, leave strict Rule-of-8 off until a true Brain MCP `create_multiSim` transport is connected. Keep MMR and structural low-correlation enabled regardless.

No path in this V2 change enables automatic submission.
