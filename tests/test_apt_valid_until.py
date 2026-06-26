"""APT: a stale (but validly-signed) Release must be rejected via Valid-Until.

Signature verification proves authenticity, not freshness; without enforcing
Valid-Until an attacker/mirror can replay an old signed Release to freeze the
repository at a vulnerable state.
"""

from __future__ import annotations

import pytest

from chantal.core.config import AptConfig, RepositoryConfig, SignatureVerificationConfig
from chantal.core.gpg_verify import SignatureVerificationError
from chantal.plugins.apt.sync import AptSyncPlugin

_PAST = "Thu, 01 Jan 2009 00:00:00 UTC"
_FUTURE = "Thu, 01 Jan 2099 00:00:00 UTC"


def _syncer(*, enabled=True, policy="fail"):
    verify = SignatureVerificationConfig(
        enabled=enabled, keys=["dummy"], on_invalid_signature=policy
    )
    config = RepositoryConfig(
        id="deb",
        name="Deb",
        type="apt",
        feed="http://example.com/ubuntu",
        apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
        verify=verify,
    )
    return AptSyncPlugin(storage=None, config=config)


def test_expired_release_fails_under_fail_policy():
    with pytest.raises(SignatureVerificationError, match="expired"):
        _syncer(policy="fail")._enforce_release_freshness(_PAST)


def test_expired_release_warns_under_warn_policy():
    # warn policy logs but does not raise.
    _syncer(policy="warn")._enforce_release_freshness(_PAST)


def test_future_release_is_accepted():
    _syncer(policy="fail")._enforce_release_freshness(_FUTURE)


def test_no_valid_until_is_accepted():
    _syncer(policy="fail")._enforce_release_freshness(None)


def test_unparseable_valid_until_does_not_raise():
    _syncer(policy="fail")._enforce_release_freshness("not a date")


def test_verification_disabled_skips_enforcement():
    # With verification off the Release isn't trusted anyway -> no enforcement.
    _syncer(enabled=False, policy="fail")._enforce_release_freshness(_PAST)
