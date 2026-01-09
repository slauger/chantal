"""
Database connection management for Chantal.

This module provides utilities for creating and managing database connections.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from chantal.db.models import Base


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self, database_url: str, echo: bool = False):
        """Initialize database manager.

        Args:
            database_url: SQLAlchemy database URL (e.g., postgresql://user:pass@host/dbname)
            echo: Whether to echo SQL statements (useful for debugging)
        """
        self.database_url = database_url
        self.engine: Engine = create_engine(database_url, echo=echo)
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

    def create_all(self) -> None:
        """Create all database tables.

        Note: In production, use Alembic migrations instead.
        This is mainly for testing and development.
        """
        Base.metadata.create_all(bind=self.engine)

    def drop_all(self) -> None:
        """Drop all database tables.

        WARNING: This is destructive! Use only for testing.
        """
        Base.metadata.drop_all(bind=self.engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        """Provide a transactional scope for database operations.

        Usage:
            with db_manager.session() as session:
                package = session.query(Package).filter_by(sha256=sha256).first()
                if not package:
                    package = Package(...)
                    session.add(package)
                session.commit()
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session(self) -> Session:
        """Get a new database session.

        Note: Caller is responsible for closing the session.
        Prefer using the session() context manager instead.
        """
        return self.SessionLocal()


def get_database_manager(database_url: str, echo: bool = False) -> DatabaseManager:
    """Factory function to create a DatabaseManager instance.

    Args:
        database_url: SQLAlchemy database URL
        echo: Whether to echo SQL statements

    Returns:
        DatabaseManager instance
    """
    return DatabaseManager(database_url, echo=echo)
