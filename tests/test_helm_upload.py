"""Unit tests for Helm Chart.yaml parsing and `chantal package upload` (helm path).

Builds synthetic chart .tgz archives (gzipped tar with <chart>/Chart.yaml) so
the pure-Python Chart.yaml extraction, metadata mapping, and the dedup /
conflict / --force matrix are exercised without the helm binary or docker.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chantal.cli.package_commands import _upload_helm
from chantal.core.config import StorageConfig
from chantal.core.storage import StorageManager
from chantal.db.models import Base, ContentItem, Repository
from chantal.plugins.helm.chart import ChartFormatError, parse_chart_metadata

_CHART = {
    "apiVersion": "v2",
    "name": "demo",
    "version": "0.1.0",
    "appVersion": "1.16.0",
    "description": "A demo chart",
    "type": "application",
    "keywords": ["demo", "test"],
    "maintainers": [{"name": "Simon Lauger", "email": "simon@lauger.de"}],
}


def _add(tar: tarfile.TarFile, name: str, content: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    tar.addfile(info, io.BytesIO(content))


def _build_chart(chart: dict | None = None, extra_files: dict[str, bytes] | None = None) -> bytes:
    chart = chart if chart is not None else _CHART
    root = chart["name"]
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add(tar, f"{root}/Chart.yaml", yaml.safe_dump(chart).encode())
        _add(tar, f"{root}/values.yaml", b"replicaCount: 1\n")
        for path, content in (extra_files or {}).items():
            _add(tar, f"{root}/{path}", content)
    return buf.getvalue()


def _parse_bytes(data: bytes) -> dict:
    """parse_chart_metadata takes a Path, so spill the bytes to a temp file."""
    with tempfile.NamedTemporaryFile(suffix=".tgz", delete=False) as f:
        f.write(data)
        path = Path(f.name)
    return parse_chart_metadata(path)


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
    repo = Repository(repo_id="internal", name="Internal", type="helm", feed="", mode="HOSTED")
    session.add(repo)
    session.commit()
    return repo


def _helm_items(repository: Repository) -> list[ContentItem]:
    return [i for i in repository.content_items if i.content_type == "helm"]


def test_parse_chart_metadata():
    meta = _parse_bytes(_build_chart())
    assert meta["name"] == "demo"
    assert meta["version"] == "0.1.0"
    assert meta["appVersion"] == "1.16.0"


def test_parse_chart_picks_toplevel_over_subchart():
    """A bundled subchart's Chart.yaml must not shadow the top-level one."""
    sub = yaml.safe_dump({"apiVersion": "v2", "name": "dep", "version": "9.9.9"}).encode()
    data = _build_chart(extra_files={"charts/dep/Chart.yaml": sub})
    meta = _parse_bytes(data)
    assert meta["name"] == "demo"  # not "dep"
    assert meta["version"] == "0.1.0"


def test_parse_chart_rejects_non_gzip():
    with pytest.raises(ChartFormatError):
        _parse_bytes(b"not a gzip tarball")


def test_parse_chart_rejects_archive_without_chart_yaml():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add(tar, "demo/values.yaml", b"replicaCount: 1\n")
    with pytest.raises(ChartFormatError, match="no Chart.yaml"):
        _parse_bytes(buf.getvalue())


def test_parse_chart_rejects_chart_yaml_missing_name_version():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add(tar, "demo/Chart.yaml", yaml.safe_dump({"apiVersion": "v2"}).encode())
    with pytest.raises(ChartFormatError, match="missing required"):
        _parse_bytes(buf.getvalue())


def test_parse_chart_rejects_non_dict_chart_yaml():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add(tar, "demo/Chart.yaml", b"- just\n- a\n- list\n")
    with pytest.raises(ChartFormatError, match="missing required"):
        _parse_bytes(buf.getvalue())


def test_parse_chart_rejects_oversized_chart_yaml():
    """A chart whose Chart.yaml expands to a huge size must be refused, not read."""
    # ~4 MiB of highly-compressible YAML -> a few KB gzipped (a bomb), over the
    # 1 MiB Chart.yaml cap.
    bomb = ("a: " + "A" * (4 * 1024 * 1024) + "\nname: demo\nversion: 0.1.0\n").encode()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _add(tar, "demo/Chart.yaml", bomb)
    with pytest.raises(ChartFormatError, match="too large|maximum allowed size"):
        _parse_bytes(buf.getvalue())


def test_upload_maps_chart_fields(session, storage, repository, tmp_path):
    f = tmp_path / "demo-0.1.0.tgz"
    f.write_bytes(_build_chart())
    assert _upload_helm(session, storage, repository, f, force=False) == "uploaded"

    item = _helm_items(repository)[0]
    meta = item.content_metadata
    assert item.name == "demo"
    assert item.version == "0.1.0"
    assert meta["app_version"] == "1.16.0"
    assert meta["description"] == "A demo chart"
    assert meta["keywords"] == ["demo", "test"]
    # digest/urls are filled by the publisher, not the uploaded item.
    assert meta.get("digest") is None
    assert meta.get("urls") is None


def test_upload_then_link_same_bytes(session, storage, repository, tmp_path):
    f = tmp_path / "demo-0.1.0.tgz"
    f.write_bytes(_build_chart())
    assert _upload_helm(session, storage, repository, f, force=False) == "uploaded"
    assert _upload_helm(session, storage, repository, f, force=False) == "linked"
    assert len(_helm_items(repository)) == 1


def test_same_name_version_different_content_requires_force(session, storage, repository, tmp_path):
    a = tmp_path / "a.tgz"
    a.write_bytes(_build_chart())
    b = tmp_path / "b.tgz"
    b.write_bytes(
        _build_chart({**_CHART, "description": "changed"})
    )  # same name/version, diff bytes

    assert _upload_helm(session, storage, repository, a, force=False) == "uploaded"
    with pytest.raises(ValueError, match="already present"):
        _upload_helm(session, storage, repository, b, force=False)
    assert len(_helm_items(repository)) == 1
    assert _helm_items(repository)[0].content_metadata["description"] == "A demo chart"

    assert _upload_helm(session, storage, repository, b, force=True) == "replaced"
    items = _helm_items(repository)
    assert len(items) == 1
    assert items[0].content_metadata["description"] == "changed"
