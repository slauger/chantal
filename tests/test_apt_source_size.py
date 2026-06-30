"""APT: a non-numeric Size in a Sources stanza must skip that artifact, not
abort the whole sync."""

from __future__ import annotations

from chantal.core.config import AptConfig, RepositoryConfig
from chantal.plugins.apt.models import SourcesMetadata
from chantal.plugins.apt.sync import AptSyncPlugin


def _syncer():
    config = RepositoryConfig(
        id="deb",
        name="Deb",
        type="apt",
        feed="http://example.com/ubuntu",
        apt=AptConfig(distribution="jammy", components=["main"], architectures=["amd64"]),
    )
    return AptSyncPlugin(storage=None, config=config)


def test_non_numeric_source_size_is_skipped_not_raised():
    src = SourcesMetadata(
        package="demo",
        version="1.0",
        directory="pool/main/d/demo",
        checksums_sha256=[
            {"filename": "demo_1.0.dsc", "checksum": "a" * 64, "size": "123"},
            {"filename": "demo_1.0.tar.gz", "checksum": "b" * 64, "size": "NOTANUMBER"},
        ],
    )

    artifacts = _syncer()._flatten_source_artifacts([src])

    names = {a["filename"] for a in artifacts}
    assert names == {"demo_1.0.dsc"}  # the bad-size artifact is skipped, no raise
    assert next(a for a in artifacts if a["filename"] == "demo_1.0.dsc")["size"] == 123
