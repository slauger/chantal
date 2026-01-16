#!/usr/bin/env python3
"""
Auto-format YAML files to fix comment indentation warnings.

This script fixes yamllint comment-indentation warnings by ensuring that
comment lines within commented-out blocks have consistent indentation.
"""

import sys
from pathlib import Path
from typing import List


def format_yaml_file(file_path: Path) -> bool:
    """
    Format a YAML file by fixing comment indentation.

    yamllint requires that comments be indented to match the content they describe.
    Within list items (starting with -), comments should be indented to match
    the list content (usually 2 spaces).

    Args:
        file_path: Path to the YAML file to format

    Returns:
        True if file was modified, False otherwise
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        modified = False
        result_lines = []

        # Track the current indentation context
        expected_comment_indent = 0

        for i, line in enumerate(lines):
            stripped = line.lstrip(' ')
            indent = len(line) - len(stripped)

            # Detect list item markers (- id:, - name:, etc.)
            if stripped.startswith('- '):
                # Start of a list item - set expected comment indent
                expected_comment_indent = indent + 2  # Comments within item should be +2
                result_lines.append(line)
                continue

            # Detect when we leave a list item context (back to root level non-comment)
            if indent == 0 and stripped and not stripped.startswith('#'):
                expected_comment_indent = 0

            # Handle comment lines
            if stripped.startswith('#'):
                # Standalone # line (empty comment separator)
                if stripped.strip() == '#':
                    # These should match the surrounding context
                    proper_indent = expected_comment_indent if expected_comment_indent > 0 else 0

                    if indent != proper_indent:
                        fixed_line = ' ' * proper_indent + '#\n'
                        result_lines.append(fixed_line)
                        modified = True
                        continue

                # Comment with content - check if it's part of a list item
                elif expected_comment_indent > 0 and indent < expected_comment_indent:
                    # This comment is under-indented relative to the list item
                    # Fix it by adding proper indentation
                    fixed_line = ' ' * expected_comment_indent + stripped
                    result_lines.append(fixed_line)
                    modified = True
                    continue

                result_lines.append(line)
            else:
                result_lines.append(line)

        if modified:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(result_lines)
            return True

        return False

    except Exception as e:
        print(f"Error processing {file_path}: {e}", file=sys.stderr)
        return False


def find_yaml_files(directories: List[str]) -> List[Path]:
    """
    Find all YAML files in the specified directories.

    Args:
        directories: List of directory paths to search

    Returns:
        List of Path objects for YAML files
    """
    yaml_files = []
    for directory in directories:
        dir_path = Path(directory)
        if dir_path.exists() and dir_path.is_dir():
            yaml_files.extend(dir_path.rglob('*.yaml'))
            yaml_files.extend(dir_path.rglob('*.yml'))
    return sorted(yaml_files)


def main() -> int:
    """Main entry point."""
    # Directories to process
    directories = ['examples', '.dev', '.github']

    print("Finding YAML files...")
    yaml_files = find_yaml_files(directories)

    if not yaml_files:
        print("No YAML files found.")
        return 0

    print(f"Found {len(yaml_files)} YAML files\n")

    modified_count = 0
    for yaml_file in yaml_files:
        if format_yaml_file(yaml_file):
            print(f"✓ Formatted: {yaml_file}")
            modified_count += 1

    if modified_count > 0:
        print(f"\n✓ Formatted {modified_count} file(s)")
    else:
        print("\n✓ All files already properly formatted")

    return 0


if __name__ == '__main__':
    sys.exit(main())
