from harnessy.context import DropOldest, estimate_tokens, find_cut

from .helpers import TASK, history


def test_cut_is_at_an_assistant_turn_and_fits():
    h = history(10)
    i = find_cut(h, 1000)
    assert h[i].role == "assistant"
    assert estimate_tokens([h[0], *h[i:]]) <= 1000
    assert estimate_tokens([h[0], *h[i - 2 :]]) > 1000  # it is the earliest cut that fits


def test_min_cut_is_respected():
    h = history(10)
    assert find_cut(h, 10**6, min_cut=5) == 5
    assert find_cut(h, 10**6, min_cut=4) == 5  # 4 is a user turn: move to the next assistant turn


def test_falls_back_to_the_last_assistant_turn():
    h = history(10)
    assert find_cut(h, 1) == len(h) - 2


def test_no_assistant_turn():
    assert find_cut([TASK], 10) == 1


def test_drop_oldest_view_is_given():
    h = history(6)
    assert DropOldest().view(h, 5) == [h[0], *h[5:]]
    assert DropOldest.reserve_tokens == 0
