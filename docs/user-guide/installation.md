# Installation

## Requirements

- **Python 3.10+** (required for `Path.hardlink_to()`)
- **PostgreSQL or SQLite** (for metadata storage)

## Installation Steps

### 1. Clone the Repository

```bash
git clone https://github.com/slauger/chantal.git
cd chantal
```

### 2. Install in Development Mode

```bash
pip install -e .
```

### 3. Verify Installation

```bash
chantal --version
```

## Dependencies

Chantal will automatically install the following dependencies:

- **SQLAlchemy** - Database ORM
- **Click** - CLI framework
- **Requests** - HTTP client
- **PyYAML** - Configuration file parsing
- **lxml** - XML parsing for repository metadata
- **Pydantic** - Configuration validation

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
