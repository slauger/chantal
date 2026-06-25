# Installation

## Requirements

- **Python 3.12+** (required for `Path.hardlink_to()`)
- **PostgreSQL or SQLite** (for metadata storage)

## Installation Steps

### Install from PyPI (Recommended)

Chantal is published on [PyPI](https://pypi.org/project/chantal/):

```bash
pip install chantal
```

Verify the installation:

```bash
chantal --version
```

### Install from Source

To work on Chantal or run an unreleased version, install from a checkout in
editable mode:

```bash
git clone https://github.com/slauger/chantal.git
cd chantal
pip install -e .
```

For development (linters, tests), install the optional `dev` extras:

```bash
pip install -e ".[dev]"
```

## Dependencies

Chantal automatically installs the following dependencies:

- **click** - CLI framework
- **pydantic** - Configuration validation
- **pyyaml** - Configuration file parsing
- **packaging** - Version parsing/comparison
- **sqlalchemy** - Database ORM
- **psycopg2-binary** - PostgreSQL driver
- **alembic** - Database schema migrations
- **requests** / **urllib3** - HTTP client and downloads
- **zstandard** - Zstandard metadata compression
- **python-gnupg** - GPG signing (APT/RPM filtered mode)
- **cryptography** - RSA signing of APK indexes (APKINDEX.tar.gz)
- **tqdm** - Progress bars
- **rich** - Terminal output formatting

## Database Setup

### SQLite (Development)

SQLite is the default and requires no additional setup:

```yaml
database:
  url: sqlite:///chantal.db
```

### PostgreSQL (Production)

For production environments, PostgreSQL is recommended:

1. Install PostgreSQL:
   ```bash
   # Ubuntu/Debian
   sudo apt install postgresql postgresql-contrib

   # RHEL/CentOS
   sudo dnf install postgresql-server postgresql-contrib
   sudo postgresql-setup --initdb
   sudo systemctl enable --now postgresql
   ```

2. Create database and user:
   ```sql
   CREATE DATABASE chantal;
   CREATE USER chantal WITH PASSWORD 'your-password';
   GRANT ALL PRIVILEGES ON DATABASE chantal TO chantal;
   ```

3. Update configuration:
   ```yaml
   database:
     url: postgresql://chantal:your-password@localhost/chantal
   ```

## Next Steps

After installation, proceed to the [Quick Start](quickstart.md) guide.
