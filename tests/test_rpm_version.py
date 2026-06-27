"""Tests for RPM EVR comparison and the only_latest_version filter."""

from __future__ import annotations

import pytest

from chantal.plugins.rpm.filters import keep_only_latest_versions
from chantal.plugins.rpm.version import evr_compare, rpmvercmp


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ("1.0", "1.0", 0),
        ("9.el9", "10.el9", -1),  # the headline bug: numeric segment length
        ("1.0", "1.0.1", -1),
        ("2.0", "2.0~rc1", 1),  # tilde sorts before the release
        ("2.0~rc1", "2.0~rc2", -1),
        ("1.0^20230101", "1.0", 1),  # caret sorts after the end
        ("1.0", "1.0^x", -1),
        ("1.a", "1.1", -1),  # numeric segment outranks alphabetic
        ("1.0", "1.00", 0),  # leading zeros ignored
        ("fc36", "fc37", -1),
    ],
)
def test_rpmvercmp(a, b, expected):
    assert rpmvercmp(a, b) == expected
    assert rpmvercmp(b, a) == -expected


def test_evr_compare_epoch_and_release():
    # Epoch dominates everything.
    assert evr_compare(1, "1.0", "1", 0, "9.0", "9") == 1
    # Same epoch+version: release compared with rpmvercmp (10 > 9).
    assert evr_compare(0, "1.0", "9.el9", 0, "1.0", "10.el9") == -1


def test_only_latest_version_filter_uses_evr():
    def pkg(version, release, epoch="0"):
        return {
            "name": "demo",
            "arch": "x86_64",
            "version": version,
            "release": release,
            "epoch": epoch,
        }

    packages = [
        pkg("1.0", "9.el9"),
        pkg("1.0", "10.el9"),  # newest by EVR (PEP 440/lexical would pick 9.el9)
        pkg("1.0", "1.el9"),
    ]
    result = keep_only_latest_versions(packages, n=1)
    assert len(result) == 1
    assert result[0]["release"] == "10.el9"


def test_only_latest_version_epoch_wins():
    def pkg(version, epoch):
        return {
            "name": "demo",
            "arch": "x86_64",
            "version": version,
            "release": "1",
            "epoch": epoch,
        }

    # 2.0 looks newer, but epoch 1 on the 1.0 build wins.
    result = keep_only_latest_versions([pkg("2.0", "0"), pkg("1.0", "1")], n=1)
    assert result[0]["version"] == "1.0"
