"""M0v: pure strict claims never become a real trusted writer authorization."""
from __future__ import annotations

from dataclasses import fields, replace

import pytest

from scripts.m0v_credential_origin_review import (
    OriginClaims, OriginDecision, assess,
)


def _all_claimed() -> OriginClaims:
    return OriginClaims(**{
        field.name: (
            False if field.name == "untrusted_old_code_with_both_credentials_wrote"
            else True
        )
        for field in fields(OriginClaims)
    })


def test_all_asserted_true_and_bypass_false_still_no_go():
    d = assess(_all_claimed())
    assert d == OriginDecision(
        "NO_GO_CREDENTIAL_AND_EXECUTION_ORIGIN_NOT_INDEPENDENTLY_ATTESTED"
    )
    assert not d.authorizes_migration
    assert not d.authorizes_policy_install
    assert not d.authorizes_root_trial


@pytest.mark.parametrize("name", [
    f.name for f in fields(OriginClaims)
    if f.name != "untrusted_old_code_with_both_credentials_wrote"
])
@pytest.mark.parametrize("bad", [False, None, 0, 1, "yes", []])
def test_no_implicit_bools_in_positive_review(name, bad):
    d = assess(replace(_all_claimed(), **{name: bad}))
    assert d.decision == "NO_GO_UNVERIFIED_" + name.upper()
    assert not d.authorizes_root_trial


def test_same_credential_old_code_bypass_is_always_explicit():
    d = assess(OriginClaims(untrusted_old_code_with_both_credentials_wrote=True))
    assert d == OriginDecision(
        "NO_GO_UNTRUSTED_OLD_CODE_CAN_BORROW_WRITER_AUTHORITY"
    )


@pytest.mark.parametrize("bad", [None, 1, 0, "no", [], {}])
def test_unknown_old_code_with_credentials_state_is_no_go(bad):
    d = assess(replace(
        _all_claimed(),
        untrusted_old_code_with_both_credentials_wrote=bad,
    ))
    assert d.decision == (
        "NO_GO_UNVERIFIED_UNTRUSTED_OLD_CODE_WITH_BOTH_CREDENTIALS_WROTE"
    )


@pytest.mark.parametrize("bad", [None, True, False, 1, 0, {}, []])
def test_invalid_claim_object_is_rejected(bad):
    assert assess(bad) == OriginDecision("NO_GO_INVALID_ORIGIN_CLAIMS")
