"""Tests for CLI module."""

import pytest
from click.testing import CliRunner

from chantal.cli.main import cli


def test_cli_version():
    """Test that --version works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "version" in result.output.lower()


def test_cli_help():
    """Test that --help works."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Chantal" in result.output
    assert "every other name" in result.output


def test_repo_list():
    """Test repo list command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["repo", "list"])
    assert result.exit_code == 0
    assert "Configured Repositories" in result.output


def test_snapshot_list():
    """Test snapshot list command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["snapshot", "list"])
    assert result.exit_code == 0
    assert "snapshots" in result.output.lower()
