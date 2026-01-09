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


def test_package_list():
    """Test package list command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["package", "list", "--repo-id", "test-repo"])
    assert result.exit_code == 0
    assert "test-repo" in result.output


def test_package_search():
    """Test package search command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["package", "search", "nginx"])
    assert result.exit_code == 0
    assert "nginx" in result.output


def test_package_show():
    """Test package show command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["package", "show", "nginx-1.20.1-10.el9.x86_64"])
    assert result.exit_code == 0
    assert "nginx" in result.output


def test_stats():
    """Test stats command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["stats"])
    assert result.exit_code == 0
    assert "Statistics" in result.output


def test_repo_check_updates():
    """Test repo check-updates command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["repo", "check-updates", "--repo-id", "test-repo"])
    assert result.exit_code == 0
    assert "test-repo" in result.output


def test_db_stats():
    """Test db stats command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["db", "stats"])
    assert result.exit_code == 0
    assert "Database Statistics" in result.output


def test_db_verify():
    """Test db verify command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["db", "verify"])
    assert result.exit_code == 0
    assert "integrity" in result.output.lower()
