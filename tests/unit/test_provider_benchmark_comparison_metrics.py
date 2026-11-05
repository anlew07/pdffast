from tools.provider_benchmark.comparison_metrics import compare_texts


def test_overlap_identical_and_reordered_characters():
    full = compare_texts("研究内容。\n项目目标", "研究内容。 项目目标")
    assert full["char_overlap_pct"] == 100
    assert full["trigram_overlap_pct"] == 100
    reordered = compare_texts("甲乙丙丁", "丁丙乙甲")
    assert reordered["char_overlap_pct"] == 100
    assert reordered["trigram_overlap_pct"] == 0


def test_missing_text_and_symmetric_score():
    assert compare_texts("", "")["char_overlap_pct"] is None
    assert compare_texts("", "")["trigram_overlap_pct"] is None
    assert compare_texts("", "你好")["char_overlap_pct"] == 0
    left = compare_texts("北京大学", "北京邮电大学")
    right = compare_texts("北京邮电大学", "北京大学")
    assert left["char_overlap_pct"] == right["char_overlap_pct"]
    assert left["trigram_overlap_pct"] == right["trigram_overlap_pct"]
    assert left["char_delta"] == -right["char_delta"]


def test_short_text_is_supported():
    assert compare_texts("啊", "啊")["trigram_overlap_pct"] == 100
    assert compare_texts("甲乙", "甲丙")["trigram_overlap_pct"] == 0
