from atendeio.analytics.tracker import PersonTracker


def box(x):  # pessoa de 0.1 de largura andando no eixo x
    return (x, 0.2, x + 0.1, 0.8)


def test_id_is_stable_while_moving():
    t, ids = PersonTracker(), []
    for i in range(10):
        ids.append(t.update([box(0.1 + i * 0.01)], now=i * 0.1)[0][0])
    assert len(set(ids)) == 1


def test_two_people_keep_distinct_ids():
    t = PersonTracker()
    a, b = t.update([box(0.1), box(0.7)], 0.0)
    a2, b2 = t.update([box(0.11), box(0.71)], 0.1)
    assert (a[0], b[0]) == (a2[0], b2[0]) and a[0] != b[0]


def test_short_occlusion_keeps_id_long_one_does_not():
    t = PersonTracker(max_age_s=1.5)
    pid = t.update([box(0.4)], 0.0)[0][0]
    t.update([], 0.5)
    assert t.update([box(0.4)], 1.0)[0][0] == pid          # voltou em 1 s: mesmo id
    t.update([], 1.1)
    assert t.update([box(0.4)], 5.0)[0][0] != pid          # sumiu 3,9 s: id novo


def test_new_person_gets_new_id():
    t = PersonTracker()
    first = t.update([box(0.1)], 0.0)[0][0]
    ids = [i for i, _ in t.update([box(0.1), box(0.8)], 0.1)]
    assert ids[0] == first and ids[1] != first
