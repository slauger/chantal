from __future__ import annotations

"""Centralized output handling for sync operations."""

from enum import Enum
from typing import Any

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)


class OutputLevel(Enum):
    """Output verbosity level."""

    QUIET = 0  # Only errors
    NORMAL = 1  # Standard with progress bar
    VERBOSE = 2  # All details


class SyncOutputter:
    """Centralized output handler for sync operations.

    Handles output formatting for quiet/normal/verbose modes with progress bars.
    """

    def __init__(self, level: OutputLevel = OutputLevel.NORMAL):
        """Initialize sync outputter.

        Args:
            level: Output verbosity level
        """
        self.level = level
        self.console = Console()
        self.err_console = Console(stderr=True)
        self.progress: Progress | None = None
        self.task: TaskID | None = None

    def header(self, repo_id: str, repo_type: str, feed_url: str, **kwargs: Any) -> None:
        """Show repository header.

        Args:
            repo_id: Repository ID
            repo_type: Repository type (rpm, apt, helm, apk)
            feed_url: Feed URL
            **kwargs: Additional key-value pairs to display
        """
        if self.level == OutputLevel.QUIET:
            return

        type_name = repo_type.upper()
        self.console.print(f"Syncing {type_name} repository: {repo_id}", style="bold")
        self.console.print(f"Feed URL: {feed_url}")

        # Print additional kwargs
        for key, value in kwargs.items():
            # Convert key from snake_case to Title Case
            display_key = key.replace("_", " ").title()
            self.console.print(f"{display_key}: {value}")

        self.console.print()

    def phase(self, name: str, number: int | None = None) -> None:
        """Show phase marker.

        Args:
            name: Phase name
            number: Optional phase number
        """
        if self.level == OutputLevel.QUIET:
            return

        if number is not None:
            self.console.print(f"\n=== Phase {number}: {name} ===", style="bold cyan")
        else:
            self.console.print(f"\n=== {name} ===", style="bold cyan")

    def start_progress(
        self, total: int, description: str = "Processing", unit: str = "items"
    ) -> None:
        """Start progress bar.

        Args:
            total: Total number of items
            description: Progress description
            unit: Unit name for items
        """
        if self.level != OutputLevel.NORMAL:
            return

        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("({task.completed}/{task.total} {task.fields[unit]})"),
            TimeRemainingColumn(),
            console=self.console,
        )
        self.progress.start()
        self.task = self.progress.add_task(description, total=total, unit=unit)

    def start_download_progress(
        self, total_bytes: int, description: str = "Downloading"
    ) -> None:
        """Start download progress bar with transfer speed.

        Args:
            total_bytes: Total bytes to download
            description: Progress description
        """
        if self.level != OutputLevel.NORMAL:
            return

        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
            console=self.console,
        )
        self.progress.start()
        self.task = self.progress.add_task(description, total=total_bytes)

    def update_progress(self, advance: int = 1) -> None:
        """Update progress bar.

        Args:
            advance: Number of items/bytes to advance
        """
        if self.progress and self.task is not None:
            self.progress.update(self.task, advance=advance)

    def finish_progress(self) -> None:
        """Finish and cleanup progress bar."""
        if self.progress:
            self.progress.stop()
            self.progress = None
            self.task = None

    def info(self, message: str) -> None:
        """Show info message.

        Args:
            message: Info message
        """
        if self.level == OutputLevel.QUIET:
            return

        self.console.print(message)

    def verbose(self, message: str) -> None:
        """Show verbose message.

        Args:
            message: Verbose message
        """
        if self.level != OutputLevel.VERBOSE:
            return

        self.console.print(message)

    def success(self, message: str) -> None:
        """Show success message.

        Args:
            message: Success message
        """
        if self.level == OutputLevel.QUIET:
            return

        self.console.print(f"✓ {message}", style="green")

    def warning(self, message: str) -> None:
        """Show warning message.

        Args:
            message: Warning message
        """
        if self.level == OutputLevel.QUIET:
            return

        self.console.print(f"⚠️  {message}", style="yellow")

    def error(self, message: str) -> None:
        """Show error message (always shown, even in quiet mode).

        Args:
            message: Error message
        """
        self.err_console.print(f"✗ {message}", style="red")

    def downloading(
        self, package_name: str, size_mb: float, current: int, total: int
    ) -> None:
        """Show package download status.

        In NORMAL mode: Updates progress bar
        In VERBOSE mode: Prints detailed line

        Args:
            package_name: Package name
            size_mb: Package size in MB
            current: Current package number (1-indexed)
            total: Total number of packages
        """
        if self.level == OutputLevel.VERBOSE:
            self.console.print(
                f"→ Package {current}/{total}: {package_name} ({size_mb:.1f} MB)"
            )

    def already_in_pool(self, package_name: str, sha256: str | None = None) -> None:
        """Show that package is already in pool.

        Args:
            package_name: Package name
            sha256: Optional SHA256 hash (first 16 chars)
        """
        if self.level != OutputLevel.VERBOSE:
            return

        if sha256:
            self.console.print(
                f"  → Already in pool: {package_name} (SHA256: {sha256[:16]}...)"
            )
        else:
            self.console.print(f"  → Already in pool: {package_name}")

    def downloaded(self, size_mb: float, duration_s: float | None = None) -> None:
        """Show download completion.

        Args:
            size_mb: Downloaded size in MB
            duration_s: Optional duration in seconds
        """
        if self.level != OutputLevel.VERBOSE:
            return

        if duration_s:
            speed_mbs = size_mb / duration_s if duration_s > 0 else 0
            self.console.print(
                f"  → Downloaded {size_mb:.1f} MB in {duration_s:.1f}s ({speed_mbs:.1f} MB/s)"
            )
        else:
            self.console.print(f"  → Downloaded {size_mb:.1f} MB")

    def summary(self, **stats: Any) -> None:
        """Show summary statistics.

        Args:
            **stats: Statistics as key-value pairs
        """
        if self.level == OutputLevel.QUIET:
            return

        self.console.print("\n=== Summary ===", style="bold")
        for key, value in stats.items():
            # Convert key from snake_case to Title Case
            display_key = key.replace("_", " ").title()
            self.console.print(f"  {display_key}: {value}")
