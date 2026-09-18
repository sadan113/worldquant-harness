# Private Low-Correlation Profile v1

This fork adds a private diversification layer on top of the upstream WorldQuant harness.

## Goals

- Reuse the mature upstream lifecycle, platform checks, memory, and no-submit boundary.
- Avoid public-template crowding by screening structural clones before simulation and presubmit.
- Prefer candidates from different field families and operator families.
- Keep real submission explicit. This profile does not enable automatic submission.

## What changed

The module `worldquant_harness/wq_lowcorr.py` adds:

- normalized structural fingerprints,
- field-family classification,
- operator-family classification,
- coarse horizon buckets,
- structure-aware similarity,
- nearest-neighbor search against active/virtual-active inventory,
- MMR candidate selection for quality/diversity balance.

The presubmit workflow now has an additional private low-correlation gate. The default structural cutoff is `0.60`.

## Recommended first run

```powershell
python scripts/wq_agent_workflow.py presubmit-sequential `
  --output-dir reports/wq_agent_runs/private_lowcorr_usa_d1 `
  --candidate-files <candidate_file.jsonl> `
  --region USA `
  --universe TOP3000 `
  --delay 1 `
  --target-ready 3 `
  --max-total-simulations 120 `
  --cycle-candidate-count 8 `
  --virtual-similarity-cutoff 0.65 `
  --private-lowcorr-cutoff 0.60 `
  --max-virtual-family-count 2 `
  --max-virtual-field-signature-count 1
```

This path does not submit.

## Correlation policy

Do not treat SELF_CORRELATION failures as a parameter-tuning problem by default. Once a strong candidate fails correlation, the next repair should change at least two of:

1. field family,
2. dataset/source family,
3. operator family,
4. time horizon,
5. neutralization family.

Changing only decay, truncation, or a nearby time window is considered a settings-only mutation and should have low priority.

## Public system risk

Open source code is not itself the correlation problem. Crowding occurs when many researchers reuse the same search space: identical seed formulas, fields, operator skeletons, and small parameter perturbations. Keep this fork's private candidate recipes and research memory out of the public repository if they encode proprietary search directions.
