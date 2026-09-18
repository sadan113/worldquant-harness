from worldquant_harness.wq_lowcorr import (
    compute_lowcorr_similarity,
    fingerprint_expression,
    mmr_select_candidates,
)


def test_lowcorr_detects_same_family_window_clone():
    a = "rank(ts_mean(anl4_afv4_eps_mean, 30))"
    b = "rank(ts_zscore(anl4_afv4_eps_mean, 60))"
    sim = compute_lowcorr_similarity(a, b)
    assert sim["field_family_overlap"] == 1.0
    assert sim["overall_similarity"] >= 0.55


def test_lowcorr_separates_different_economic_families():
    a = "rank(ts_mean(anl4_afv4_eps_mean, 30))"
    b = "rank(ts_corr(vwap, volume, 30))"
    sim = compute_lowcorr_similarity(a, b)
    assert sim["field_family_overlap"] < 1.0
    assert sim["overall_similarity"] < 0.60


def test_fingerprint_contains_structural_features():
    fp = fingerprint_expression("rank(ts_corr(vwap, volume, 30))")
    assert "price_volume" in fp["field_families"]
    assert "ts_relation" in fp["operator_families"]
    assert fp["skeleton"]


def test_mmr_prefers_diverse_candidate_over_clone():
    rows = [
        {
            "expression": "rank(ts_mean(anl4_afv4_eps_mean, 30))",
            "source_family": "earnings_revision",
            "quality_score": 1.0,
        },
        {
            "expression": "rank(ts_zscore(anl4_afv4_eps_mean, 60))",
            "source_family": "earnings_revision",
            "quality_score": 0.95,
        },
        {
            "expression": "rank(ts_corr(vwap, volume, 30))",
            "source_family": "price_volume_relation",
            "quality_score": 0.80,
        },
    ]
    selected = mmr_select_candidates(
        rows,
        limit=2,
        diversity_lambda=0.50,
        hard_similarity_cutoff=0.70,
        max_source_family_count=1,
    )
    assert len(selected) == 2
    assert {row["source_family"] for row in selected} == {
        "earnings_revision",
        "price_volume_relation",
    }
