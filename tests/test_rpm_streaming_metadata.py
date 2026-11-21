"""Bounded-memory handling of large RPM repository metadata (#152).

RHEL 9 BaseOS ships a primary.xml that decompresses to ~1.3 GB (AppStream
filelists: ~1.8 GB). Decompressing such files in one piece and building an
ElementTree of them ran a 4 GB host out of memory, so sync and publish must
stream them. These tests generate a synthetic repository large enough that a
whole-document approach blows well past the memory bounds asserted here.
"""

from __future__ import annotations

import gzip
import io
import tracemalloc
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from chantal.core.config import RepositoryConfig
from chantal.db.connection import DatabaseManager
from chantal.db.models import Base, ContentItem, Repository, RepositoryMode
from chantal.plugins.rpm.publisher import RpmPublisher
from chantal.plugins.rpm.sync import RpmSyncPlugin

COMMON_NS = "http://linux.duke.edu/metadata/common"
RPM_NS = "http://linux.duke.edu/metadata/rpm"
FILELISTS_NS = "http://linux.duke.edu/metadata/filelists"

# Packages in the synthetic repository: names x versions. Each package carries
# a description and a file list, so the documents are tens of MB uncompressed.
NAMES = 600
VERSIONS = 40
# Peak traced allocations allowed while processing them. A whole-document
# ElementTree of the synthetic data needs 100-300 MB; streaming needs ~3 MB.
MEMORY_LIMIT = 16 * 1024 * 1024

DESCRIPTION = "Synthetic package used to exercise streaming metadata handling. " * 6


def _packages() -> Iterator[tuple[str, str, str]]:
    for n in range(NAMES):
        for v in range(VERSIONS):
            yield f"pkg{n:04d}", f"1.{v}", f"{v + 1}.el9"


def _write_primary(path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=1) as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write(
            f'<metadata xmlns="{COMMON_NS}" xmlns:rpm="{RPM_NS}" '
            f'packages="{NAMES * VERSIONS}">\n'
        )
        for i, (name, ver, rel) in enumerate(_packages()):
            files = "".join(f"<file>/usr/share/{name}/{ver}/f{j}</file>" for j in range(8))
            requires = "".join(f'<rpm:entry name="lib{j}.so()(64bit)"/>' for j in range(10))
            fh.write(
                f'<package type="rpm"><name>{name}</name><arch>x86_64</arch>'
                f'<version epoch="0" ver="{ver}" rel="{rel}"/>'
                f'<checksum type="sha256" pkgid="YES">{i:064x}</checksum>'
                f"<summary>{name}</summary><description>{DESCRIPTION}</description>"
                f'<time file="1700000000" build="1700000000"/>'
                f'<size package="1000" installed="2000" archive="3000"/>'
                f'<location href="Packages/{name[3]}/{name}-{ver}-{rel}.x86_64.rpm"/>'
                f"<format><rpm:license>MIT</rpm:license><rpm:group>Unspecified</rpm:group>"
                f"<rpm:sourcerpm>{name}-{ver}-{rel}.src.rpm</rpm:sourcerpm>"
                f"<rpm:requires>{requires}</rpm:requires>{files}</format></package>\n"
            )
        fh.write("</metadata>\n")


def _write_filelists(path: Path) -> None:
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=1) as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write(f'<filelists xmlns="{FILELISTS_NS}" packages="{NAMES * VERSIONS}">\n')
        for i, (name, ver, rel) in enumerate(_packages()):
            files = "".join(f"<file>/usr/share/{name}/{ver}/file{j}</file>" for j in range(40))
            fh.write(
                f'<package pkgid="{i:064x}" name="{name}" arch="x86_64">'
                f'<version epoch="0" ver="{ver}" rel="{rel}"/>{files}</package>\n'
            )
        fh.write("</filelists>\n")


@pytest.fixture(scope="module")
def big_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Upstream repository dir with a large primary and filelists."""
    root = tmp_path_factory.mktemp("bigrepo")
    (root / "repodata").mkdir()
    _write_primary(root / "repodata" / "primary.xml.gz")
    _write_filelists(root / "repodata" / "filelists.xml.gz")
    return root


def _peak(fn: Callable[[], Any]) -> tuple[Any, int]:
    tracemalloc.start()
    try:
        result = fn()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, peak


def _content_item(name: str, ver: str, rel: str) -> ContentItem:
    return ContentItem(
        content_type="rpm",
        name=name,
        version=ver,
        sha256="0" * 64,
        size_bytes=1000,
        pool_path=f"00/00/{name}.rpm",
        filename=f"{name}-{ver}-{rel}.x86_64.rpm",
        content_metadata={"arch": "x86_64", "release": rel, "epoch": "0"},
    )


# Published set: the newest version of the first 20 names.
LATEST = [(f"pkg{n:04d}", f"1.{VERSIONS - 1}", f"{VERSIONS}.el9") for n in range(20)]


class _FakeResponse:
    def __init__(self, path: Path) -> None:
        self._path = path

    def raise_for_status(self) -> None:
        pass

    @property
    def content(self) -> bytes:
        return self._path.read_bytes()

    def iter_content(self, chunk_size: int = 1) -> Iterator[bytes]:
        with open(self._path, "rb") as fh:
            yield from iter(lambda: fh.read(chunk_size), b"")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


class _FakeSession:
    """Serves files from a local directory for any ``get(base/url)``."""

    def __init__(self, root: Path, base: str) -> None:
        self.root = root
        self.base = base

    def get(self, url: str, **_: Any) -> _FakeResponse:
        return _FakeResponse(self.root / url.removeprefix(self.base + "/"))


def _write_repomd(root: Path) -> None:
    import hashlib

    primary = root / "repodata" / "primary.xml.gz"
    digest = hashlib.sha256(primary.read_bytes()).hexdigest()
    (root / "repodata" / "repomd.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<repomd xmlns="http://linux.duke.edu/metadata/repo">'
        '<data type="primary">'
        f'<checksum type="sha256">{digest}</checksum>'
        '<location href="repodata/primary.xml.gz"/>'
        f"<size>{primary.stat().st_size}</size>"
        "</data></repomd>"
    )


def test_check_updates_streams_primary(big_repo: Path) -> None:
    """Fetching and filtering the upstream primary keeps memory bounded."""
    _write_repomd(big_repo)
    db = DatabaseManager("sqlite:///:memory:")
    Base.metadata.create_all(db.engine)
    session = db.get_session()
    repo = Repository(repo_id="big", name="Big", type="rpm", feed="http://up", mode="MIRROR")
    session.add(repo)
    session.commit()

    config = RepositoryConfig(
        id="big",
        name="Big",
        type="rpm",
        feed="http://up",
        filters={
            "patterns": {"include": ["^pkg000[0-9]$"]},
            "post_processing": {"only_latest_version": True},
        },
    )
    plugin = RpmSyncPlugin(storage=None, config=config)
    plugin.session = _FakeSession(big_repo, "http://up")  # type: ignore[assignment]
    plugin.cache = None

    result, peak = _peak(lambda: plugin.check_updates(session, repo))

    assert result.success, result.error_message
    assert sorted(u.name for u in result.updates_available) == [f"pkg000{n}" for n in range(10)]
    assert {u.remote_version for u in result.updates_available} == {f"1.{VERSIONS - 1}"}
    assert peak < MEMORY_LIMIT, f"peak {peak / 2**20:.0f} MiB"


@pytest.fixture
def publish_dir(big_repo: Path, tmp_path: Path) -> Path:
    """repodata/ of a publish target holding hardlinks of the upstream files."""
    repodata = tmp_path / "repodata"
    repodata.mkdir()
    for name in ("primary.xml.gz", "filelists.xml.gz"):
        (repodata / f"upstream-{name}").hardlink_to(big_repo / "repodata" / name)
    return repodata


def _publisher() -> RpmPublisher:
    return RpmPublisher(storage=None)  # type: ignore[arg-type]


def test_regenerate_primary_streams(publish_dir: Path) -> None:
    packages = [_content_item(*nvr) for nvr in LATEST]
    upstream = publish_dir / "upstream-primary.xml.gz"
    metadata = [("primary", upstream)]

    (updated, regenerated), peak = _peak(
        lambda: _publisher()._regenerate_primary(
            packages, publish_dir, RepositoryMode.FILTERED, "gzip", metadata
        )
    )

    assert regenerated
    assert peak < MEMORY_LIMIT, f"peak {peak / 2**20:.0f} MiB"
    out = updated[0][1]
    assert out == publish_dir / "primary.xml.gz"
    assert not upstream.exists()
    text = gzip.decompress(out.read_bytes()).decode()
    root = ET.fromstring(text)
    assert root.get("packages") == str(len(LATEST))
    pkgs = root.findall(f"{{{COMMON_NS}}}package")
    assert [p.findtext(f"{{{COMMON_NS}}}name") for p in pkgs] == [n for n, _, _ in LATEST]
    hrefs = {p.find(f"{{{COMMON_NS}}}location").get("href") for p in pkgs}  # type: ignore[union-attr]
    assert hrefs == {f"Packages/{n}-{v}-{r}.x86_64.rpm" for n, v, r in LATEST}
    # Same document shape as createrepo_c: namespaces declared once on the root,
    # rpm: prefix preserved (libsolv matches it literally).
    assert text.count("xmlns=") == 1
    assert text.count("xmlns:rpm=") == 1
    assert "<rpm:requires>" in text and "ns0:" not in text
    # The upstream package bodies are kept verbatim.
    assert pkgs[0].find(f"{{{COMMON_NS}}}format/{{{RPM_NS}}}requires") is not None


def test_filter_filelists_streams(publish_dir: Path) -> None:
    packages = [_content_item(*nvr) for nvr in LATEST]
    source = publish_dir / "upstream-filelists.xml.gz"
    metadata = [("filelists", source)]

    updated, peak = _peak(
        lambda: _publisher()._filter_and_regenerate_filelists(packages, publish_dir, metadata)
    )

    assert peak < MEMORY_LIMIT, f"peak {peak / 2**20:.0f} MiB"
    out = updated[0][1]
    assert out == source
    root = ET.fromstring(gzip.decompress(out.read_bytes()))
    assert root.get("packages") == str(len(LATEST))
    assert len(root.findall(f"{{{FILELISTS_NS}}}package")) == len(LATEST)


def test_repomd_open_checksum_streams(big_repo: Path, tmp_path: Path) -> None:
    import hashlib

    source = big_repo / "repodata" / "filelists.xml.gz"
    repomd, peak = _peak(
        lambda: _publisher()._generate_repomd_xml(tmp_path, [("filelists", source)])
    )

    assert peak < MEMORY_LIMIT, f"peak {peak / 2**20:.0f} MiB"
    open_data = gzip.decompress(source.read_bytes())
    ns = "{http://linux.duke.edu/metadata/repo}"
    data = ET.parse(repomd).getroot().find(f"{ns}data")
    assert data is not None
    assert data.findtext(f"{ns}open-checksum") == hashlib.sha256(open_data).hexdigest()
    assert data.findtext(f"{ns}open-size") == str(len(open_data))
    assert data.findtext(f"{ns}checksum") == hashlib.sha256(source.read_bytes()).hexdigest()


def test_parse_primary_xml_matches_streaming(big_repo: Path) -> None:
    """The bytes wrapper and the streaming parser return the same packages."""
    from chantal.plugins.rpm import parsers

    data = gzip.decompress((big_repo / "repodata" / "primary.xml.gz").read_bytes())
    head = data[: data.index(b"<package", 2000)] + b"</metadata>"
    listed = parsers.parse_primary_xml(head)
    streamed = list(parsers.iter_primary_packages(io.BytesIO(head)))
    assert listed == streamed
    assert listed and listed[0]["name"] == "pkg0000"
    assert listed[0]["license"] == "MIT"
    assert listed[0]["sourcerpm"] == "pkg0000-1.0-1.el9.src.rpm"


def test_keep_only_latest_versions_matches_sort() -> None:
    """The streaming top-N equals a stable descending sort per (name, arch)."""
    import random

    from chantal.plugins.rpm.filters import keep_only_latest_versions
    from chantal.plugins.rpm.version import evr_pkg_key

    rng = random.Random(152)
    pkgs = [
        {
            "name": f"p{rng.randrange(5)}",
            "arch": rng.choice(["x86_64", "noarch"]),
            "epoch": "0",
            "version": f"1.{rng.randrange(4)}",
            "release": f"{rng.randrange(3)}.el9",
            "i": i,  # distinguishes equal-EVR duplicates
        }
        for i in range(400)
    ]

    for n in (1, 2, 5):
        grouped: dict[tuple[str, str], list[dict]] = {}
        for pkg in pkgs:
            grouped.setdefault((pkg["name"], pkg["arch"]), []).append(pkg)
        expected = [
            pkg
            for group in grouped.values()
            for pkg in sorted(group, key=evr_pkg_key, reverse=True)[:n]
        ]
        assert keep_only_latest_versions(iter(pkgs), n=n) == expected


class TestFetchedMetadataFile:
    @pytest.fixture
    def upstream(self, tmp_path: Path) -> tuple[_FakeSession, str]:
        import hashlib

        root = tmp_path / "up"
        (root / "repodata").mkdir(parents=True)
        payload = gzip.compress(b"<metadata/>")
        (root / "repodata" / "primary.xml.gz").write_bytes(payload)
        return _FakeSession(root, "http://up"), hashlib.sha256(payload).hexdigest()

    def test_download_is_cached_and_reused(self, upstream, tmp_path: Path) -> None:
        from chantal.core.cache import MetadataCache
        from chantal.plugins.rpm import parsers

        session, digest = upstream
        cache = MetadataCache(cache_path=tmp_path / "cache", enabled=True)
        with parsers.fetched_metadata_file(
            session, "http://up", "repodata/primary.xml.gz", digest, cache, "primary"
        ) as (path, from_cache):
            assert not from_cache
            assert path == tmp_path / "cache" / f"{digest}.xml.gz"
            with parsers.open_metadata(path, "repodata/primary.xml.gz") as stream:
                assert stream.read() == b"<metadata/>"
        assert path.exists()
        assert [p.name for p in (tmp_path / "cache").iterdir()] == [path.name]

        with parsers.fetched_metadata_file(
            session, "http://up", "repodata/primary.xml.gz", digest, cache, "primary"
        ) as (_, from_cache):
            assert from_cache

    def test_without_cache_temp_file_is_removed(self, upstream) -> None:
        from chantal.plugins.rpm import parsers

        session, digest = upstream
        with parsers.fetched_metadata_file(
            session, "http://up", "repodata/primary.xml.gz", digest, None, "primary"
        ) as (path, from_cache):
            assert not from_cache and path.exists()
        assert not path.exists()

    def test_checksum_mismatch_leaves_nothing_behind(self, upstream, tmp_path: Path) -> None:
        from chantal.core.cache import MetadataCache
        from chantal.plugins.rpm import parsers

        session, _ = upstream
        cache = MetadataCache(cache_path=tmp_path / "cache", enabled=True)
        with pytest.raises(ValueError, match="checksum mismatch"):
            with parsers.fetched_metadata_file(
                session, "http://up", "repodata/primary.xml.gz", "a" * 64, cache, "primary"
            ):
                pytest.fail("a mismatching download must not be handed out")
        assert list((tmp_path / "cache").iterdir()) == []


def test_parsed_cache_key_covers_filters() -> None:
    base = {"id": "r", "name": "r", "type": "rpm", "feed": "http://up"}
    checksum = "c" * 64

    def key(**extra: Any) -> str | None:
        return RpmSyncPlugin(
            storage=None, config=RepositoryConfig(**base, **extra)
        )._parsed_cache_key(checksum)

    assert key() == checksum
    latest = key(filters={"post_processing": {"only_latest_version": True}})
    latest_n = key(filters={"post_processing": {"only_latest_n_versions": 2}})
    assert latest and latest_n and len({checksum, latest, latest_n}) == 3
    # Relative to "now": the result changes over time, so it is never cached.
    assert key(filters={"metadata": {"build_time": {"last_n_days": 7}}}) is None


def test_filtering_replaces_hardlink_without_touching_pool(big_repo: Path, publish_dir: Path):
    """The published hardlink is replaced; the upstream/pool blob stays intact."""
    import hashlib

    pool_blob = big_repo / "repodata" / "filelists.xml.gz"
    before = hashlib.sha256(pool_blob.read_bytes()).hexdigest()
    packages = [_content_item(*nvr) for nvr in LATEST]
    source = publish_dir / "upstream-filelists.xml.gz"

    _publisher()._filter_and_regenerate_filelists(packages, publish_dir, [("filelists", source)])

    assert hashlib.sha256(pool_blob.read_bytes()).hexdigest() == before
    assert source.stat().st_ino != pool_blob.stat().st_ino
    assert sorted(p.name for p in publish_dir.iterdir()) == [
        "upstream-filelists.xml.gz",
        "upstream-primary.xml.gz",
    ]


@pytest.mark.parametrize("suffix", [".gz", ".xz", ".bz2", ".zst", ".xml"])
def test_filter_metadata_file_round_trip(tmp_path: Path, suffix: str) -> None:
    """Every supported compression is read and written as a stream; namespaces,
    xml:lang, non-ASCII text and nested foreign namespaces survive."""
    from chantal.plugins.rpm.compression import open_compressed_writer, open_decompressed
    from chantal.plugins.rpm.xmlstream import filter_metadata_file

    doc = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<metadata xmlns="{COMMON_NS}" xmlns:rpm="{RPM_NS}" xml:lang="en" packages="3">'
        '<package type="rpm"><name>keep</name><summary>Grüße &amp; &lt;tags&gt;</summary>'
        "<format><rpm:license>MIT</rpm:license>"
        '<x:extra xmlns:x="urn:extra">1</x:extra></format></package>'
        '<package type="rpm"><name>drop</name></package>'
        '<package type="rpm"><name>keep</name></package>'
        "</metadata>"
    )
    src = tmp_path / f"src.xml{suffix}" if suffix != ".xml" else tmp_path / "src.xml"
    with open_compressed_writer(src, src.suffix) as fh:
        fh.write(doc.encode())
    dest = tmp_path / f"out{src.suffix if suffix != '.xml' else '.xml'}"

    def keep(elem: ET.Element) -> bool:
        return elem.findtext(f"{{{COMMON_NS}}}name") == "keep"

    assert filter_metadata_file(src, dest, "package", keep) == (3, 2)

    with open_decompressed(dest) as stream:
        text = stream.read().decode()
    root = ET.fromstring(text)
    assert root.get("packages") == "2"
    assert root.get("{http://www.w3.org/XML/1998/namespace}lang") == "en"
    pkgs = root.findall(f"{{{COMMON_NS}}}package")
    assert [p.findtext(f"{{{COMMON_NS}}}name") for p in pkgs] == ["keep", "keep"]
    assert pkgs[0].findtext(f"{{{COMMON_NS}}}summary") == "Grüße & <tags>"
    assert pkgs[0].findtext(f"{{{COMMON_NS}}}format/{{urn:extra}}extra") == "1"
    assert "<rpm:license>" in text
    assert not list(tmp_path.glob(".*.tmp"))


def test_filter_updateinfo_streams(tmp_path: Path) -> None:
    """Advisories are kept verbatim when one of their packages is published."""
    repodata = tmp_path / "repodata"
    repodata.mkdir()
    updates = []
    # One advisory per (name, version); the newest version of the first 20
    # names is published.
    nvrs = [(f"pkg{n:04d}", f"1.{v}", f"{v + 1}.el9") for n in range(500) for v in range(VERSIONS)]
    for i, (name, ver, rel) in enumerate(nvrs):
        updates.append(
            f'<update from="test" status="final" type="bugfix" version="2.0">'
            f"<id>RHBA-2026:{i:05d}</id><title>Update {i}</title>"
            f'<issued date="2026-01-01 00:00:00"/><description>{DESCRIPTION}</description>'
            f'<pkglist><collection short="c"><name>c</name>'
            f'<package name="{name}" version="{ver}" release="{rel}" epoch="0" arch="x86_64">'
            f"<filename>{name}-{ver}-{rel}.x86_64.rpm</filename></package>"
            f"</collection></pkglist></update>"
        )
    upstream = repodata / "updateinfo.xml.gz"
    upstream.write_bytes(
        gzip.compress(
            ('<?xml version="1.0"?>\n<updates>' + "".join(updates) + "</updates>").encode()
        )
    )
    packages = [_content_item(*nvr) for nvr in LATEST]

    updated, peak = _peak(
        lambda: _publisher()._filter_and_regenerate_updateinfo(
            packages, repodata, [("updateinfo", upstream)]
        )
    )

    assert peak < MEMORY_LIMIT, f"peak {peak / 2**20:.0f} MiB"
    root = ET.fromstring(gzip.decompress(updated[0][1].read_bytes()))
    kept = root.findall("update")
    published = {f"{n}-{v}-{r}" for n, v, r in LATEST}
    assert len(kept) == len(LATEST)
    for update in kept:
        pkg = update.find("pkglist/collection/package")
        assert pkg is not None
        assert f"{pkg.get('name')}-{pkg.get('version')}-{pkg.get('release')}" in published
        assert update.findtext("description") == DESCRIPTION


def test_put_file_failure_keeps_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed cache store must not remove the caller's verified download."""
    import hashlib
    import os

    from chantal.core.cache import MetadataCache

    cache = MetadataCache(cache_path=tmp_path / "cache", enabled=True)
    src = tmp_path / "download.tmp"
    src.write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()

    def fail(*_: object) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr(os, "replace", fail)
    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError):
        cache.put_file(digest, src, "primary")
    assert src.read_bytes() == b"payload"
    assert not list((tmp_path / "cache").iterdir())
