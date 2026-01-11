from __future__ import annotations

"""
RPM package filtering logic.

This module provides functions for filtering RPM packages based on various criteria.
"""

import re
from collections import defaultdict
from datetime import datetime, timedelta

from packaging import version

from chantal.core.config import (
    FilterConfig,
    GenericMetadataFilterConfig,
    ListFilterConfig,
    PatternFilterConfig,
    PostProcessingConfig,
    RpmFilterConfig,
)


def apply_filters(packages: list[dict], filters: FilterConfig) -> list[dict]:
    """Apply package filters using generic filter engine.

    Args:
        packages: List of package metadata dicts
        filters: Filter configuration

    Returns:
        Filtered list of packages
    """
    # Normalize legacy config to new structure
    filters = filters.normalize()

    # Validate filter config for RPM repository
    filters.validate_for_repo_type("rpm")

    filtered_packages = []

    for pkg in packages:
        # Apply generic metadata filters
        if filters.metadata:
            if not check_generic_metadata_filters(pkg, filters.metadata):
                continue

        # Apply RPM-specific filters
        if filters.rpm:
            if not check_rpm_filters(pkg, filters.rpm):
                continue

        # Apply pattern filters
        if filters.patterns:
            if not check_pattern_filters(pkg, filters.patterns):
                continue

        # Package passed all filters
        filtered_packages.append(pkg)

    # Apply post-processing (after all filters)
    if filters.post_processing:
        filtered_packages = apply_post_processing(filtered_packages, filters.post_processing)

    return filtered_packages


def check_generic_metadata_filters(pkg: dict, metadata: GenericMetadataFilterConfig) -> bool:
    """Check if package passes generic metadata filters.

    Args:
        pkg: Package metadata dict
        metadata: Generic metadata filter config

    Returns:
        True if package passes all generic metadata filters
    """
    # Size filter
    if metadata.size_bytes:
        size_bytes = pkg.get("size_bytes", 0)
        if metadata.size_bytes.min and size_bytes < metadata.size_bytes.min:
            return False
        if metadata.size_bytes.max and size_bytes > metadata.size_bytes.max:
            return False

    # Build time filter
    build_time = pkg.get("build_time")
    if metadata.build_time and build_time:
        # Convert package build_time (Unix timestamp) to datetime
        pkg_build_dt = datetime.fromtimestamp(build_time)

        if metadata.build_time.newer_than:
            newer_than_dt = datetime.fromisoformat(metadata.build_time.newer_than)
            if pkg_build_dt < newer_than_dt:
                return False

        if metadata.build_time.older_than:
            older_than_dt = datetime.fromisoformat(metadata.build_time.older_than)
            if pkg_build_dt > older_than_dt:
                return False

        if metadata.build_time.last_n_days:
            cutoff_dt = datetime.now() - timedelta(days=metadata.build_time.last_n_days)
            if pkg_build_dt < cutoff_dt:
                return False

    # Architecture filter
    if metadata.architectures:
        arch = pkg.get("arch", "")
        if not check_list_filter(arch, metadata.architectures):
            return False

    return True


def check_rpm_filters(pkg: dict, rpm_filters: RpmFilterConfig) -> bool:
    """Check if package passes RPM-specific filters.

    Args:
        pkg: Package metadata dict
        rpm_filters: RPM filter config

    Returns:
        True if package passes all RPM filters
    """
    # Source RPM filter
    if rpm_filters.exclude_source_rpms:
        if pkg.get("arch") == "src":
            return False
        # Also check if this is a source RPM by looking at sourcerpm field
        # (Note: binary RPMs have sourcerpm pointing to the .src.rpm they were built from)
        # We only want to exclude actual source RPMs (arch == "src")

    # Group filter
    group = pkg.get("group")
    if rpm_filters.groups and group:
        if not check_list_filter(group, rpm_filters.groups):
            return False

    # License filter
    license_str = pkg.get("license")
    if rpm_filters.licenses and license_str:
        if not check_list_filter(license_str, rpm_filters.licenses):
            return False

    # Vendor filter
    vendor = pkg.get("vendor")
    if rpm_filters.vendors and vendor:
        if not check_list_filter(vendor, rpm_filters.vendors):
            return False

    # Epoch filter
    epoch = pkg.get("epoch")
    if rpm_filters.epochs and epoch:
        if not check_list_filter(epoch, rpm_filters.epochs):
            return False

    return True


def check_list_filter(value: str, list_filter: ListFilterConfig) -> bool:
    """Check if value passes list filter (include/exclude).

    Args:
        value: Value to check
        list_filter: List filter config

    Returns:
        True if value passes filter
    """
    # Check include list
    if list_filter.include:
        if value not in list_filter.include:
            return False

    # Check exclude list
    if list_filter.exclude:
        if value in list_filter.exclude:
            return False

    return True


def check_pattern_filters(pkg: dict, patterns: PatternFilterConfig) -> bool:
    """Check if package passes pattern filters.

    Args:
        pkg: Package metadata dict
        patterns: Pattern filter config

    Returns:
        True if package passes all pattern filters
    """
    pkg_name = pkg.get("name", "")
    pkg_version = pkg.get("version", "")
    pkg_release = pkg.get("release", "")
    pkg_arch = pkg.get("arch", "")
    pkg_name_full = f"{pkg_name}-{pkg_version}-{pkg_release}.{pkg_arch}"

    # Include patterns - at least one must match
    if patterns.include:
        matched = False
        for pattern in patterns.include:
            if re.search(pattern, pkg_name) or re.search(pattern, pkg_name_full):
                matched = True
                break
        if not matched:
            return False

    # Exclude patterns - none must match
    if patterns.exclude:
        for pattern in patterns.exclude:
            if re.search(pattern, pkg_name) or re.search(pattern, pkg_name_full):
                return False

    return True


def apply_post_processing(packages: list[dict], post_proc: PostProcessingConfig) -> list[dict]:
    """Apply post-processing to filtered packages.

    Args:
        packages: Filtered packages
        post_proc: Post-processing config

    Returns:
        Post-processed packages
    """
    if post_proc.only_latest_version:
        return keep_only_latest_versions(packages, n=1)
    elif post_proc.only_latest_n_versions:
        return keep_only_latest_versions(packages, n=post_proc.only_latest_n_versions)

    return packages


def keep_only_latest_versions(packages: list[dict], n: int = 1) -> list[dict]:
    """Keep only the latest N versions of each package (by name and arch).

    Args:
        packages: List of package metadata dicts
        n: Number of versions to keep (default: 1)

    Returns:
        Filtered list with only latest N versions per (name, arch)
    """
    # Group packages by (name, arch)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for pkg in packages:
        name = pkg.get("name", "")
        arch = pkg.get("arch", "")
        key = (name, arch)
        grouped[key].append(pkg)

    # For each group, keep only latest N versions
    result = []
    for (name, arch), pkg_list in grouped.items():
        # Sort by version (newest first)
        # Use tuple comparison: (epoch, version, release) for RPM version semantics
        try:
            sorted_pkgs = sorted(
                pkg_list,
                key=lambda p: (
                    int(p.get("epoch", 0) or 0),  # Epoch as int
                    version.parse(p.get("version", "")),  # Parse version
                    p.get("release", ""),  # Release as string
                ),
                reverse=True,
            )
        except Exception as e:
            # If version parsing fails, fall back to simple tuple comparison
            print(f"Warning: Version parsing failed for {name}.{arch}: {e}")
            sorted_pkgs = sorted(
                pkg_list,
                key=lambda p: (
                    int(p.get("epoch", 0) or 0),
                    p.get("version", ""),
                    p.get("release", ""),
                ),
                reverse=True,
            )

        # Keep only latest N versions
        result.extend(sorted_pkgs[:n])

    return result
