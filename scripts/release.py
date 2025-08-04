#!/usr/bin/env python3

import sys
import subprocess
import re
import tomllib
import tomli_w
import json
from pathlib import Path


def run_command(cmd, cwd=None, check=True):
    """Run a shell command and return the result."""
    print(f"Running: {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error running command: {cmd}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        sys.exit(1)
    return result


def validate_version(version):
    """Validate version format."""
    if not re.match(r'^\d+\.\d+\.\d+$', version):
        print("Error: Version must be in format X.Y.Z (e.g., 1.0.0)")
        sys.exit(1)


def update_python_version(version):
    """Update Python package version in pyproject.toml."""
    print("Updating Python package version...")
    pyproject_path = Path("packages/python/pyproject.toml")

    with open(pyproject_path, 'rb') as f:
        data = tomllib.load(f)

    data['project']['version'] = version

    with open(pyproject_path, 'wb') as f:
        tomli_w.dump(data, f)

    print(f"Updated Python package version to {version}")


def update_javascript_version(version):
    """Update JavaScript package version in package.json."""
    print("Updating JavaScript package version...")
    package_json_path = Path("packages/js/package.json")

    with open(package_json_path, 'r') as f:
        data = json.load(f)

    data['version'] = version

    with open(package_json_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"Updated JavaScript package version to {version}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/release.py <version> [--dry-run]")
        print("Example: python scripts/release.py 1.0.0")
        print("Example: python scripts/release.py 1.0.0 --dry-run")
        sys.exit(1)

    version = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    validate_version(version)

    if dry_run:
        print(f"🧪 DRY RUN: Preparing release version {version}...")
        print("This will simulate the release process without making any changes.")
    else:
        print(f"Preparing release version {version}...")

    try:
        # Update Python package version
        update_python_version(version)

        # Update JavaScript package version
        update_javascript_version(version)

        if dry_run:
            print("🧪 DRY RUN: Would stage changes...")
            print("🧪 DRY RUN: Would commit version changes...")
            print("🧪 DRY RUN: Would create and push tag...")
            print(f"🧪 DRY RUN: Release {version} simulation completed!")
            print("To perform the actual release, run without --dry-run flag")

            # Revert the changes in dry-run mode
            print("🧪 DRY RUN: Reverting changes...")
            run_command("git checkout -- packages/python/pyproject.toml packages/js/package.json")
            print("🧪 DRY RUN: Changes reverted successfully!")
        else:
            # Stage changes
            print("Staging version changes...")
            run_command("git add packages/python/pyproject.toml packages/js/package.json")

            # Commit version changes
            print("Committing version changes...")
            run_command(f'git commit -m "Bump version to {version}"')

            # Create and push tag
            print("Creating and pushing tag...")
            run_command(f"git tag v{version}")
            run_command("git push origin main")
            run_command(f"git push origin v{version}")

            print(f"✅ Release {version} prepared successfully!")
            print("The CI will automatically build and publish both packages.")
            print(f"GitHub Release will be created at: https://github.com/pydantic/genai-prices/releases/tag/v{version}")

    except Exception as e:
        print(f"❌ Release preparation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
