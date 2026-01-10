# Creating Custom Plugins

Guide to creating custom plugins for Chantal.

## Overview

Custom plugins allow you to extend Chantal to support new repository types. Each repository type requires:

1. **Sync Plugin** - Fetch and store packages
2. **Publisher Plugin** - Generate publishable repositories

## Prerequisites

- Python 3.10+
- Understanding of Chantal's architecture
- Knowledge of target repository format

## Step 1: Create Plugin Files

Create new files in `src/chantal/plugins/`:

```
src/chantal/plugins/
├── __init__.py
├── base.py               # Base classes (already exists)
├── my_plugin_sync.py     # Your sync plugin
└── my_plugin.py          # Your publisher plugin
```

## Step 2: Implement Sync Plugin

### Basic Structure

```python
# src/chantal/plugins/my_plugin_sync.py

from chantal.plugins.base import SyncPlugin
from chantal.core.storage import StorageManager
from sqlalchemy.orm import Session
from chantal.db.models import Package, Repository
from chantal.core.config import RepositoryConfig

class MyPluginSync(SyncPlugin):
    def __init__(self, storage: StorageManager):
        self.storage = storage

    def sync(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig
    ) -> dict:
        """Sync repository from upstream."""

        # 1. Fetch metadata
        metadata = self.fetch_metadata(config.feed)

        # 2. Parse packages
        packages = self.parse_packages(metadata)

        # 3. Apply filters
        filtered = self.apply_filters(packages, config.filters)

        # 4. Download packages
        downloaded = 0
        skipped = 0

        for pkg_info in filtered:
            sha256 = pkg_info['sha256']
            url = pkg_info['url']
            filename = pkg_info['filename']

            # Check if package exists in pool
            if self.storage.exists(sha256, filename):
                skipped += 1
                continue

            # Download to pool
            pool_path = self.storage.add_package(url, sha256, filename)
            downloaded += 1

            # Add to database
            package = Package(
                sha256=sha256,
                filename=filename,
                size=pkg_info['size'],
                name=pkg_info['name'],
                version=pkg_info['version'],
                architecture=pkg_info['arch']
            )
            session.add(package)
            repository.packages.append(package)

        session.commit()

        return {
            'downloaded': downloaded,
            'skipped': skipped,
            'total': len(filtered)
        }

    def fetch_metadata(self, feed_url: str) -> dict:
        """Fetch repository metadata."""
        # Implement metadata fetching
        pass

    def parse_packages(self, metadata: dict) -> list:
        """Parse package list from metadata."""
        # Implement package parsing
        pass

    def apply_filters(self, packages: list, filters: dict) -> list:
        """Apply filters to package list."""
        # Implement filtering logic
        pass
```

### Helper Methods

#### HTTP Client

```python
from chantal.plugins.http_client import HttpClient

def fetch_metadata(self, feed_url: str):
    client = HttpClient(proxy_config=None, ssl_config=None)
    response = client.get(feed_url)
    return response.json()  # or response.text
```

#### Download File

```python
def download_package(self, url: str, target_path: Path):
    client = HttpClient()
    client.download_file(url, target_path)
```

## Step 3: Implement Publisher Plugin

### Basic Structure

```python
# src/chantal/plugins/my_plugin.py

from chantal.plugins.base import PublisherPlugin
from chantal.core.storage import StorageManager
from pathlib import Path
from sqlalchemy.orm import Session
from chantal.db.models import Package, Repository, Snapshot

class MyPluginPublisher(PublisherPlugin):
    def __init__(self, storage: StorageManager):
        super().__init__(storage)

    def publish_repository(
        self,
        session: Session,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path
    ):
        """Publish repository to target directory."""

        # 1. Get packages
        packages = self._get_repository_packages(session, repository)

        # 2. Create directory structure
        target_path.mkdir(parents=True, exist_ok=True)
        packages_dir = target_path / "packages"
        packages_dir.mkdir(exist_ok=True)

        # 3. Create hardlinks
        for package in packages:
            target_file = packages_dir / package.filename
            self.storage.create_hardlink(
                package.sha256,
                package.filename,
                target_file
            )

        # 4. Generate metadata
        self.generate_metadata(packages, target_path)

    def publish_snapshot(
        self,
        session: Session,
        snapshot: Snapshot,
        repository: Repository,
        config: RepositoryConfig,
        target_path: Path
    ):
        """Publish snapshot to target directory."""

        # Similar to publish_repository but use snapshot.packages
        packages = self._get_snapshot_packages(session, snapshot)

        # ... (same as publish_repository)

    def unpublish(self, target_path: Path):
        """Remove published repository."""
        if target_path.exists():
            shutil.rmtree(target_path)

    def generate_metadata(self, packages: list, target_path: Path):
        """Generate repository metadata."""
        # Implement metadata generation
        pass
```

### Metadata Generation Example

```python
def generate_metadata(self, packages: list, target_path: Path):
    """Generate repository metadata."""
    metadata_dir = target_path / "metadata"
    metadata_dir.mkdir(exist_ok=True)

    # Generate index file
    index_file = metadata_dir / "index.json"
    index_data = {
        'packages': [
            {
                'name': pkg.name,
                'version': pkg.version,
                'filename': pkg.filename,
                'sha256': pkg.sha256,
                'size': pkg.size
            }
            for pkg in packages
        ]
    }

    with open(index_file, 'w') as f:
        json.dump(index_data, f, indent=2)
```

## Step 4: Register Plugin

Update `src/chantal/plugins/__init__.py`:

```python
from .my_plugin_sync import MyPluginSync
from .my_plugin import MyPluginPublisher

SYNC_PLUGINS = {
    'rpm': RpmSyncPlugin,
    'my_type': MyPluginSync,  # Add your plugin
}

PUBLISHER_PLUGINS = {
    'rpm': RpmPublisher,
    'my_type': MyPluginPublisher,  # Add your plugin
}
```

## Step 5: Add Configuration Support

Update `src/chantal/core/config.py`:

```python
class RepositoryConfig(BaseModel):
    id: str
    name: str
    type: Literal['rpm', 'apt', 'pypi', 'my_type']  # Add your type
    feed: str
    enabled: bool = True
    # ... other fields
```

## Step 6: Write Tests

Create test file `tests/test_my_plugin.py`:

```python
import pytest
from chantal.plugins.my_plugin_sync import MyPluginSync
from chantal.plugins.my_plugin import MyPluginPublisher

def test_sync(tmp_path, db_session):
    """Test syncing packages."""
    storage = StorageManager(tmp_path / "pool")
    plugin = MyPluginSync(storage)

    repository = Repository(
        id="test-repo",
        name="Test Repository",
        type="my_type",
        feed_url="https://example.com/repo"
    )

    config = RepositoryConfig(
        id="test-repo",
        type="my_type",
        feed="https://example.com/repo"
    )

    result = plugin.sync(db_session, repository, config)

    assert result['downloaded'] > 0

def test_publish(tmp_path, db_session):
    """Test publishing repository."""
    storage = StorageManager(tmp_path / "pool")
    plugin = MyPluginPublisher(storage)

    # ... (create test data)

    target_path = tmp_path / "published"
    plugin.publish_repository(db_session, repository, config, target_path)

    assert (target_path / "metadata" / "index.json").exists()
```

## Example: Simple HTTP Archive Plugin

Complete example for a simple HTTP directory listing repository:

```python
# sync plugin
class HttpArchiveSync(SyncPlugin):
    def fetch_metadata(self, feed_url):
        # Parse HTML directory listing
        response = self.http_client.get(feed_url)
        soup = BeautifulSoup(response.text, 'html.parser')

        packages = []
        for link in soup.find_all('a'):
            href = link.get('href')
            if href.endswith('.tar.gz'):
                packages.append({
                    'name': href.replace('.tar.gz', ''),
                    'filename': href,
                    'url': f"{feed_url}/{href}"
                })
        return packages

# publisher plugin
class HttpArchivePublisher(PublisherPlugin):
    def generate_metadata(self, packages, target_path):
        # Generate simple HTML index
        html = '<html><body><ul>'
        for pkg in packages:
            html += f'<li><a href="packages/{pkg.filename}">{pkg.filename}</a></li>'
        html += '</ul></body></html>'

        index_file = target_path / 'index.html'
        index_file.write_text(html)
```

## Best Practices

1. **Error Handling**
   ```python
   try:
       metadata = self.fetch_metadata(feed_url)
   except requests.RequestException as e:
       raise SyncError(f"Failed to fetch metadata: {e}")
   ```

2. **Progress Reporting**
   ```python
   for i, pkg in enumerate(packages):
       print(f"[{i+1}/{len(packages)}] Downloading {pkg['filename']}")
       self.download_package(pkg)
   ```

3. **Checksum Verification**
   ```python
   actual_sha256 = hashlib.sha256(data).hexdigest()
   if actual_sha256 != expected_sha256:
       raise ChecksumError(f"Checksum mismatch")
   ```

4. **Atomic Updates**
   ```python
   temp_path = target_path.with_suffix('.tmp')
   try:
       self.generate_metadata(packages, temp_path)
       temp_path.rename(target_path)  # Atomic
   except Exception:
       shutil.rmtree(temp_path)
       raise
   ```

5. **Logging**
   ```python
   import logging
   logger = logging.getLogger(__name__)

   logger.info(f"Syncing repository from {feed_url}")
   logger.debug(f"Found {len(packages)} packages")
   logger.error(f"Failed to download {filename}: {error}")
   ```

## Testing Your Plugin

```bash
# Run plugin tests
pytest tests/test_my_plugin.py -v

# Test with real repository
export CHANTAL_CONFIG=.dev/config.yaml
chantal init
chantal repo sync --repo-id test-repo

# Test publishing
chantal publish repo --repo-id test-repo
```

## Contributing Your Plugin

1. Create feature branch
2. Implement plugin with tests
3. Update documentation
4. Submit pull request

See [CONTRIBUTING.md](https://github.com/slauger/chantal/blob/main/CONTRIBUTING.md)
