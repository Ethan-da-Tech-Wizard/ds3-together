#!/usr/bin/env python3
# ==============================================================================
# Program: build_upstream.py
# Programmer: Ethan-da-Tech-Wizard
# Last Modified: November 18, 2026
# Purpose: Automated compilation and patching pipeline for ds3os server binaries
#          under Linux, verifying commit integrity, applying development patches,
#          and configuring loopback-restricted build parameters.
# ==============================================================================

"""Build the pinned ds3os native development server, bound to localhost."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

# Determine top-level project root directory
# Repository root; holds upstream.lock.json and patches/.
ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=None, capture=False):
    """Execute external CLI command, checking returncode and optionally capturing stdout."""
    return subprocess.run([str(arg) for arg in args], cwd=cwd, check=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def main():
    # Step 1: Parse command-line build and directory arguments
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "vendor/ds3os",
                        help="Path to upstream source repository checkout")
    parser.add_argument("--build", type=Path, default=ROOT / "build/ds3os",
                        help="Path to CMake build directory")
    parser.add_argument("--jobs", type=int, default=4,
                        help="Number of parallel compilation workers")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")

    # Step 2: Validate essential toolchain prerequisites (Git, CMake, C/C++ compilers)
    for tool in ("git", "cmake", "cc", "c++"):
        if not shutil.which(tool):
            parser.error(f"Install the build prerequisite: {tool}")

    source, build = args.source.resolve(), args.build.resolve()

    # Step 3: Verify cryptographic checksum of Linux development patch against lockfile
    # upstream.lock.json pins the upstream repo URL, commit and the patch hash.
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    patch = ROOT / "patches/ds3os-linux-development.patch"
    # Refuse to apply a patch that differs from the one recorded in the lock.
    if hashlib.sha256(patch.read_bytes()).hexdigest() != lock["patch_sha256"]:
        parser.error("Patch differs from upstream.lock.json; review the change first")

    # Step 4: Clone or verify pinned commit of the upstream repository
    # Shallow-fetch exactly the pinned commit rather than a branch, so the build is
    # reproducible and uses no unpinned code.
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "init", source)
        run("git", "remote", "add", "origin", lock["repository"], cwd=source)
        run("git", "fetch", "--depth", "1", "origin", lock["commit"], cwd=source)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=source)
    # Never overwrite a directory the user already has; stop instead.
    if not (source / ".git").exists():
        parser.error("Source directory exists but is not a Git checkout; preserved")
    head = run("git", "rev-parse", "HEAD", cwd=source, capture=True).decode().strip()
    # Checkout must be exactly the pinned commit.
    if head != lock["commit"]:
        parser.error("Source HEAD differs from the pinned commit; checkout preserved")
    if run("git", "diff", "--cached", "--binary", cwd=source, capture=True):
        parser.error("Source contains staged changes; preserved")

    # Step 5: Apply Linux/Proton compatibility patch modifying network listeners
    # No working-tree diff means the patch is not applied yet: check, then apply.
    # A non-empty diff must equal the patch byte-for-byte, otherwise there are
    # local edits we must not build on top of.
    diff = run("git", "diff", "--binary", "--no-ext-diff", cwd=source, capture=True)
    if not diff:
        run("git", "apply", "--check", patch, cwd=source)
        run("git", "apply", patch, cwd=source)
    elif diff != patch.read_bytes():
        parser.error("Source contains changes beyond the supplied patch; preserved")

    # Step 6: Configure CMake with loopback security isolation (-DWYLD_LOOPBACK_ONLY=ON)
    # WYLD_LOOPBACK_ONLY=ON is an option added by our patch that binds every
    # listener to 127.0.0.1.
    run("cmake", "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
        "-DWYLD_LOOPBACK_ONLY=ON")

    # Step 7: Invoke parallel native compilation targeting the Server binary
    run("cmake", "--build", build, "--target", "Server", "--parallel", args.jobs)
    print(f"Native server: {source / 'bin/x64_release/Server'}")
    print("Development infrastructure only. No seamless game adapter is installed.")


if __name__ == "__main__":
    main()
