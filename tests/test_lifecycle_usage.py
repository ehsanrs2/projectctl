from types import SimpleNamespace as NS

import pytest

from projectctl.workers.codex.usage import FIELDS, observe_usage


def test_usage_preserves_sdk_scopes_and_subset_counters():
    last = NS(input_tokens=100, output_tokens=20, cached_input_tokens=80,
              reasoning_output_tokens=10, total_tokens=120)
    total = NS(input_tokens=500, output_tokens=60, cached_input_tokens=300,
               reasoning_output_tokens=40, total_tokens=560)
    report = observe_usage(NS(usage=NS(last=last, total=total),
                              final_response="SECRET", items=["SECRET"]))
    assert report["scopes"]["last"]["total_tokens"]["value"] == 120
    assert report["scopes"]["total"]["total_tokens"]["value"] == 560
    assert "SECRET" not in str(report)
    assert "none" in report["aggregation"]


@pytest.mark.parametrize("result", [None, NS(), NS(usage=None), NS(usage=NS())])
def test_usage_unavailable_is_explicit(result):
    report = observe_usage(result)
    for counters in report["scopes"].values():
        assert set(counters) == set(FIELDS)
        assert all(x["state"] == "unknown" and x["value"] is None
                   for x in counters.values())


@pytest.mark.parametrize("value", [-1, True, 1.5, "10"])
def test_invalid_counter_is_not_coerced(value):
    report = observe_usage(NS(usage=NS(last=NS(input_tokens=value))))
    assert report["scopes"]["last"]["input_tokens"]["state"] == "unknown"


def test_installed_sdk_usage_contract_offline():
    pytest.importorskip("openai_codex")
    from openai_codex.generated.v2_all import ThreadTokenUsage, TokenUsageBreakdown
    from openai_codex._run import TurnResult
    counter = TokenUsageBreakdown(input_tokens=100, output_tokens=20,
                                 cached_input_tokens=80, reasoning_output_tokens=10,
                                 total_tokens=120)
    result = TurnResult(id="synthetic", status="completed", error=None,
                        started_at=None, completed_at=None, duration_ms=None,
                        final_response=None, items=[],
                        usage=ThreadTokenUsage(last=counter, total=counter))
    assert observe_usage(result)["scopes"]["last"]["total_tokens"]["value"] == 120


@pytest.mark.parametrize("scope", ["last", "total"])
@pytest.mark.parametrize("parent,subset", [("input_tokens", "cached_input_tokens"),
                                           ("output_tokens", "reasoning_output_tokens")])
def test_subset_cannot_exceed_parent(scope, parent, subset):
    fields = {parent: 10, subset: 999}
    other = "total" if scope == "last" else "last"
    report = observe_usage(NS(usage=NS(**{scope: NS(**fields), other: NS(**{parent: 20, subset: 5})})))
    counters = report["scopes"][scope]
    assert counters[subset] == {"state": "unknown", "value": None,
                                "reason": "sdk_subset_exceeds_parent_counter"}
    assert counters[parent]["state"] == "observed"
    assert counters[parent]["value"] == 10
    assert report["scopes"][other][subset]["value"] == 5


@pytest.mark.parametrize("parent,subset", [("input_tokens", "cached_input_tokens"),
                                           ("output_tokens", "reasoning_output_tokens")])
def test_partial_usage_does_not_invent_missing_relationship(parent, subset):
    report = observe_usage(NS(usage=NS(last=NS(**{subset: 7}), total=NS(**{parent: 9}))))
    assert report["scopes"]["last"][subset]["value"] == 7
    assert report["scopes"]["last"][parent]["state"] == "unknown"
    assert report["scopes"]["total"][parent]["value"] == 9
    assert report["scopes"]["total"][subset]["state"] == "unknown"


@pytest.mark.parametrize("count", [0, 10])
def test_subset_equal_to_parent_is_valid(count):
    counter = NS(input_tokens=count, cached_input_tokens=count,
                 output_tokens=count, reasoning_output_tokens=count)
    report = observe_usage(NS(usage=NS(last=counter, total=counter)))
    for scope in report["scopes"].values():
        for field in FIELDS[:-1]:
            assert scope[field]["state"] == "observed"
            assert scope[field]["value"] == count
