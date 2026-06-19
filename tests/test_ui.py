from __future__ import annotations

from judgment_cli import ui


def test_filter_item_indexes_matches_all_query_terms() -> None:
    items = [
        {"label": "Production App  124 traces  project-a"},
        {"label": "Support Agent  910 traces  project-b"},
        {"label": "Sandbox  2 traces  project-c"},
    ]

    matches = ui._filter_item_indexes(
        items,
        "support 910",
        label=lambda item: item["label"],
    )

    assert matches == [1]


def test_filter_item_indexes_is_case_insensitive() -> None:
    items = [{"label": "Production App"}, {"label": "Sandbox"}]

    matches = ui._filter_item_indexes(items, "prod APP", label=lambda item: item["label"])

    assert matches == [0]


def test_selector_window_centers_selected_item_when_possible() -> None:
    assert ui._selector_window(selected=50, total=100, page_size=12) == (44, 56)


def test_selector_window_stays_inside_bounds() -> None:
    assert ui._selector_window(selected=1, total=100, page_size=12) == (0, 12)
    assert ui._selector_window(selected=99, total=100, page_size=12) == (88, 100)
