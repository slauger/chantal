"""Unit tests for .deb control parsing and `chantal package upload` (deb path).

Builds synthetic .deb files (an ar archive with a control.tar.{gz,xz,zst})
so the pure-Python ar/control parser, metadata mapping, and the dedup /
conflict / --force matrix are exercised without dpkg or docker.
"""

from __future__ import annotations

import io
import lzma
import tarfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.cli.package_commands import _upload_deb
from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository
from chantal.plugins.apt.deb import DebFormatError, parse_deb_control

_CONTROL = (
    "Package: demo\n"
    "Version: 1.0\n"
    "Architecture: amd64\n"
    "Maintainer: Simon Lauger <simon@lauger.de>\n"
    "Installed-Size: 42\n"
    "Depends: libc6 (>= 2.34)\n"
    "Section: utils\n"
    "Priority: optional\n"
    "Description: a demo package\n"
    " This is the extended description.\n"
    " It spans multiple lines.\n"
)


def _ar_member(name: str, data: bytes) -> bytes:
    header = (
        name.ljust(16).encode()
        + b"0".ljust(12)  # mtime
        + b"0".ljust(6)  # uid
        + b"0".ljust(6)  # gid
        + b"100644".ljust(8)  # mode
        + str(len(data)).ljust(10).encode()  # size
        + b"`\n"
    )
    out = header + data
    if len(data) % 2:
        out += b"\n"  # pad to even length
    return out


def _control_tar(control_text: str, compression: str) -> tuple[str, bytes]:
    """Return (member_name, bytes) for a control.tar.<compression>."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        data = control_text.encode()
        info = tarfile.TarInfo("./control")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    tar_bytes = raw.getvalue()

    if compression == "gz":
        import gzip

        return "control.tar.gz", gzip.compress(tar_bytes)
    if compression == "xz":
        return "control.tar.xz", lzma.compress(tar_bytes)
    if compression == "zst":
        import zstandard as zstd

        return "control.tar.zst", zstd.ZstdCompressor().compress(tar_bytes)
    raise ValueError(compression)


def _build_deb(control_text: str = _CONTROL, compression: str = "gz") -> bytes:
    name, control_archive = _control_tar(control_text, compression)
    return b"!<arch>\n" + _ar_member("debian-binary", b"2.0\n") + _ar_member(name, control_archive)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sess = sessionmaker(bind=engine)()
    yield sess
    sess.close()


@pytest.fixture
def storage(tmp_path):
    (tmp_path / "pool").mkdir()
    return StorageManager(
        StorageConfig(
            base_path=str(tmp_path),
            pool_path=str(tmp_path / "pool"),
            published_path=str(tmp_path / "published"),
        )
    )


@pytest.fixture
def repository(session):
    repo = Repository(repo_id="internal", name="Internal", type="apt", feed="", mode="HOSTED")
    session.add(repo)
    session.commit()
    return repo


def _deb_items(repository: Repository) -> list[ContentItem]:
    return [i for i in repository.content_items if i.content_type == "deb"]


@pytest.mark.parametrize("compression", ["gz", "xz", "zst"])
def test_parse_deb_control_all_compressions(compression):
    fields = parse_deb_control(_build_deb(compression=compression))
    assert fields["Package"] == "demo"
    assert fields["Version"] == "1.0"
    assert fields["Architecture"] == "amd64"
    # Multi-line Description is joined with newlines by the RFC822 parser.
    assert fields["Description"].startswith("a demo package\n")


def test_parse_deb_control_rejects_non_deb():
    with pytest.raises(DebFormatError, match="bad ar magic"):
        parse_deb_control(b"not a deb at all")


def _ar_member_raw_size(name: str, size_str: str, data: bytes) -> bytes:
    """Build an ar member with an attacker-controlled size field."""
    header = (
        name.ljust(16).encode()
        + b"0".ljust(12)
        + b"0".ljust(6)
        + b"0".ljust(6)
        + b"100644".ljust(8)
        + size_str.ljust(10).encode()
        + b"`\n"
    )
    return header + data


def test_iter_ar_members_rejects_negative_size():
    """A negative ar size used to move the cursor backwards -> infinite loop."""
    deb = b"!<arch>\n" + _ar_member_raw_size("debian-binary", "-100", b"2.0\n")
    with pytest.raises(DebFormatError, match="negative size"):
        parse_deb_control(deb)


def test_iter_ar_members_rejects_oversized_member():
    """A size larger than the remaining archive must be rejected, not truncated."""
    deb = b"!<arch>\n" + _ar_member_raw_size("control.tar", "99999999", b"short")
    with pytest.raises(DebFormatError, match="exceeds archive"):
        parse_deb_control(deb)


def test_parse_deb_control_rejects_decompression_bomb():
    """A tiny control.tar.gz that expands past the cap must be refused."""
    # ~32 MiB of highly-compressible data in ./control -> a few KB gzipped,
    # well over the 16 MiB control.tar cap.
    deb = _build_deb("X" * (32 * 1024 * 1024), compression="gz")
    with pytest.raises(DebFormatError, match="decompression bomb|exceeds"):
        parse_deb_control(deb)


def test_upload_maps_control_fields(session, storage, repository, tmp_path):
    f = tmp_path / "demo_1.0_amd64.deb"
    f.write_bytes(_build_deb())
    assert _upload_deb(session, storage, repository, f, force=False, component="main") == "uploaded"

    item = _deb_items(repository)[0]
    meta = item.content_metadata
    assert item.name == "demo"
    assert item.version == "1.0"
    assert meta["architecture"] == "amd64"
    assert meta["component"] == "main"
    assert meta["maintainer"] == "Simon Lauger <simon@lauger.de>"
    assert meta["depends"] == "libc6 (>= 2.34)"
    assert meta["installed_size"] == 42
    # Synopsis only in description; extended text kept out of the Packages line.
    assert meta["description"] == "a demo package"
    assert "extended description" in meta["long_description"]


def test_upload_then_link_same_bytes(session, storage, repository, tmp_path):
    f = tmp_path / "demo_1.0_amd64.deb"
    f.write_bytes(_build_deb())
    assert _upload_deb(session, storage, repository, f, force=False, component="main") == "uploaded"
    assert _upload_deb(session, storage, repository, f, force=False, component="main") == "linked"
    assert len(_deb_items(repository)) == 1


def test_same_identity_different_content_requires_force(session, storage, repository, tmp_path):
    a = tmp_path / "a.deb"
    a.write_bytes(_build_deb(_CONTROL))
    b = tmp_path / "b.deb"
    b.write_bytes(_build_deb(_CONTROL.replace("Section: utils", "Section: net")))  # diff bytes

    assert _upload_deb(session, storage, repository, a, force=False, component="main") == "uploaded"
    with pytest.raises(ValueError, match="already present"):
        _upload_deb(session, storage, repository, b, force=False, component="main")
    assert len(_deb_items(repository)) == 1
    assert _deb_items(repository)[0].content_metadata["section"] == "utils"

    assert _upload_deb(session, storage, repository, b, force=True, component="main") == "replaced"
    items = _deb_items(repository)
    assert len(items) == 1
    assert items[0].content_metadata["section"] == "net"


def test_distinct_content_different_component_coexist(session, storage, repository, tmp_path):
    """Different bytes, same name/version/arch but a different component coexist."""
    a = tmp_path / "a.deb"
    a.write_bytes(_build_deb(_CONTROL))
    b = tmp_path / "b.deb"
    b.write_bytes(_build_deb(_CONTROL.replace("Section: utils", "Section: net")))

    assert _upload_deb(session, storage, repository, a, force=False, component="main") == "uploaded"
    # Different component AND different bytes -> no conflict, both kept.
    assert (
        _upload_deb(session, storage, repository, b, force=False, component="contrib") == "uploaded"
    )
    assert len(_deb_items(repository)) == 2


def test_identical_bytes_different_component_rejected(session, storage, repository, tmp_path):
    """The same bytes can't be filed under two components (global sha256 dedup)."""
    f = tmp_path / "demo.deb"
    f.write_bytes(_build_deb(_CONTROL))

    assert _upload_deb(session, storage, repository, f, force=False, component="main") == "uploaded"
    with pytest.raises(ValueError, match="already pooled under component 'main'"):
        _upload_deb(session, storage, repository, f, force=False, component="contrib")
    assert len(_deb_items(repository)) == 1
