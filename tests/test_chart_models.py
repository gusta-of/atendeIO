"""Geometria dos gráficos (porta de web/src/app/features/analytics/chart-models.spec.ts + shared/format)."""

import pytest

from atendeio.app.charts.models import bars_model, column_model, day_model, heat_model, weekly
from atendeio.app.format import compact, nice_max, num, pct


def test_axes_nice_max_and_compact():
    assert nice_max(0) == 1 and nice_max(7) == 10 and nice_max(12) == 20 and nice_max(23) == 25
    assert nice_max(0.3) == pytest.approx(0.5)
    assert compact(2.5) == "2,5" and compact(1500) == "1,5K" and compact(2000) == "2K"
    assert num(2) == "2,0" and num(None) == "–" and pct(0.834) == "83%"


class TestColumn:
    data = [{"avg": 2, "max": 4}, {"avg": None, "max": None}, {"avg": 8, "max": 10}, {"avg": 5, "max": 5}]
    m = column_model(data, label=lambda d: str(d["avg"]), x_label=lambda d, i, n: str(i))

    def test_gap_is_not_a_column_nor_zero(self):
        assert self.m["cols"][1]["rect"] is None
        assert "sem dados" in self.m["cols"][1]["tip"]["rows"][0]["text"]

    def test_peak_dot_only_when_greater_than_average(self):
        assert self.m["cols"][0]["peak_y"] is not None and self.m["cols"][3]["peak_y"] is None

    def test_labels_only_the_fullest_and_the_emptiest(self):
        assert [c["lbl"]["text"] for c in self.m["cols"] if c["lbl"]] == ["2,0", "8,0"]

    def test_axis_covers_the_peak_with_five_ticks_first_is_the_base(self):
        assert len(self.m["ticks"]) == 5 and self.m["ticks"][0]["base"] is True and self.m["ticks"][4]["label"] == "10"


class TestHeat:
    matrix = [[10 if (h == 12 and r == 2) else 5 if (h == 13 and r == 2) else None for h in range(24)] for r in range(7)]
    m = heat_model(matrix, 11, 15)

    def test_one_cell_per_hour_in_range_and_seven_rows(self):
        assert len(self.m["rows"]) == 7 and len(self.m["rows"][0]["cells"]) == 4

    def test_scale_uses_the_max_and_empty_has_no_fill(self):
        cells = self.m["rows"][2]["cells"]
        assert cells[1]["fill"] == 10 and cells[2]["fill"] == 5
        assert self.m["rows"][0]["cells"][0]["fill"] is None and self.m["max"] == 10


class TestDay:
    @staticmethod
    def s(t, avg):
        return {"t": t, "avg": avg, "max": (avg or 0) + 1, "samples": 1}

    def test_line_breaks_on_gaps_longer_than_15_minutes(self):
        m = day_model([self.s("12:00", 3), self.s("12:05", 4), self.s("13:00", 5)], 11, 15)
        assert len(m["paths"]) == 2

    def test_ignores_points_outside_the_range_and_without_data(self):
        m = day_model([self.s("03:00", 3), self.s("12:00", None)], 11, 15)
        assert m["empty"] is True and m["nearest"](100) is None

    def test_finds_the_point_nearest_to_the_cursor(self):
        m = day_model([self.s("12:00", 3), self.s("14:00", 9)], 11, 15)
        assert m["nearest"](m["W"] - m["m"]["r"])["tip"]["title"] == "14:00"


def test_long_area_names_are_abbreviated():
    m = bars_model([{"zone_id": 1, "name": "Mesa muito comprida demais", "kind": "mesa", "avg": 2, "max": 3, "samples": 10}])
    assert m["rows"][0]["name"].endswith("…") and len(m["rows"][0]["name"]) == 16


def test_weekly_is_a_weighted_average_starting_on_monday():
    w = weekly([{"date": "2026-10-26", "avg": 2, "max": 3, "samples": 100},      # segunda
                {"date": "2026-10-27", "avg": 6, "max": 9, "samples": 300},
                {"date": "2026-11-02", "avg": 1, "max": 1, "samples": 50}])
    assert len(w) == 2 and w[0]["date"] == "2026-10-26" and w[0]["avg"] == pytest.approx(5) and w[0]["max"] == 9
