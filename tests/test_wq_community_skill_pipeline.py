from worldquant_harness.wq_community_skill_pipeline import (
    STAGES,
    build_rule_of_eight_batches,
    pipeline_manifest,
)


def _rows(count: int):
    return [
        {
            "expression": f"rank(ts_mean(close, {index + 2}))",
            "tag": f"candidate-{index}",
        }
        for index in range(count)
    ]


def test_pipeline_has_five_explicit_stages():
    assert [stage.name for stage in STAGES] == [
        "knowledge_search",
        "research_recorder",
        "candidate_designer",
        "factor_backtest",
        "critic_repair",
    ]


def test_pipeline_manifest_is_no_auto_submit():
    manifest = pipeline_manifest(
        region="USA",
        universe="TOP3000",
        delay=1,
        batch_size=8,
        strict_rule_of_eight=True,
    )
    assert manifest["submit_behavior"] == "never_auto_submit"
    assert manifest["strict_rule_of_eight"] is True
    assert len(manifest["stages"]) == 5


def test_rule_of_eight_strict_keeps_only_complete_batches():
    plan = build_rule_of_eight_batches(_rows(18), batch_size=8, strict=True)
    assert plan["input_count"] == 18
    assert plan["kept_count"] == 16
    assert plan["dropped_count"] == 2
    assert [len(batch) for batch in plan["batches"]] == [8, 8]


def test_rule_of_eight_compatibility_allows_partial_final_batch():
    plan = build_rule_of_eight_batches(_rows(10), batch_size=8, strict=False)
    assert plan["kept_count"] == 10
    assert plan["dropped_count"] == 0
    assert [len(batch) for batch in plan["batches"]] == [8, 2]
