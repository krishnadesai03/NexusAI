from __future__ import annotations

from enterprise_ai.core.tool_cache import ToolCache


def test_miss_returns_missing_sentinel():
    cache = ToolCache()

    assert cache.get("search_jira_issues", {"sprint_index": 1}) is ToolCache.MISSING


def test_set_then_get_returns_the_cached_value():
    cache = ToolCache()

    cache.set("search_jira_issues", {"sprint_index": 1}, [{"key": "KAN-1"}])

    assert cache.get("search_jira_issues", {"sprint_index": 1}) == [{"key": "KAN-1"}]


def test_argument_order_does_not_affect_the_key():
    cache = ToolCache()

    cache.set("search_jira_issues", {"sprint_index": 1, "assignee": "Priya"}, ["result"])

    assert cache.get("search_jira_issues", {"assignee": "Priya", "sprint_index": 1}) == ["result"]


def test_different_arguments_are_different_cache_entries():
    cache = ToolCache()

    cache.set("search_jira_issues", {"sprint_index": 1}, ["sprint 1 result"])

    assert cache.get("search_jira_issues", {"sprint_index": 2}) is ToolCache.MISSING


def test_different_tools_with_the_same_arguments_do_not_collide():
    cache = ToolCache()

    cache.set("search_jira_issues", {"sprint_index": 1}, "jira result")

    assert cache.get("search_confluence_pages", {"sprint_index": 1}) is ToolCache.MISSING


def test_a_legitimately_falsy_cached_value_is_still_a_hit():
    cache = ToolCache()

    cache.set("search_jira_issues", {}, [])

    assert cache.get("search_jira_issues", {}) == []
