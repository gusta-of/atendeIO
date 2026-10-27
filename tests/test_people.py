from atendeio.analytics.people import PeopleCounter


def test_single_bad_frame_does_not_change_the_count():
    c = PeopleCounter(window_s=2.0)
    for t in (0.0, 0.2, 0.4, 0.6):
        assert c.update(3, t) == 3
    assert c.update(1, 0.8) == 3          # 1 frame ruim (oclusão)
    assert c.update(3, 1.0) == 3


def test_count_follows_reality_after_the_window():
    c = PeopleCounter(window_s=2.0)
    for t in (0.0, 0.5, 1.0):
        c.update(3, t)
    for t in (3.0, 3.5, 4.0):             # as amostras antigas saíram da janela
        n = c.update(1, t)
    assert n == 1


def test_empty_room():
    c = PeopleCounter()
    assert c.update(0, 0.0) == 0
