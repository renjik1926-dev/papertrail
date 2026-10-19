from papertrail.parse.normalize import normalize, normalize_text, original_span


def test_rules_in_order() -> None:
    text = "“Pay” the ﬁne—now. Make your pay-\nment  by\nMay­ 3."
    assert normalize_text(text) == '"pay" the fine-now. make your payment by may 3.'


def test_dehyphenation_only_before_lowercase() -> None:
    assert normalize_text("Smith-\nJones") == "smith- jones"
    assert normalize_text("pay-\nment") == "payment"


def test_index_map_points_back_to_original() -> None:
    text = "Make  your pay-\nment"
    norm, index_map = normalize(text)
    start = norm.index("payment")
    lo, hi = original_span(index_map, start, start + len("payment"))
    assert text[lo:hi] == "pay-\nment"
    assert normalize_text(text[lo:hi]) == "payment"
