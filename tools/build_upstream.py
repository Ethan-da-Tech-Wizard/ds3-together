#!/usr/bin/env python3
# Program: ds3-together - build_upstream.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Fetches the pinned ds3os source at an exact commit, applies this project's patch, and builds the localhost-only development server with CMake.

"""Build the pinned ds3os native development server, bound to localhost."""
# ---------------- Imports ----------------
# argparse: command-line options. hashlib: file checksums. json: read the lock file.
import argparse
import hashlib
import json
from pathlib import Path
# shutil.which finds programs on the PATH; subprocess runs external commands.
import shutil
import subprocess

# ROOT is the repository folder (two levels up from this file).
ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=None, capture=False):
    """Run an external command (every argument converted to text) and stop on failure.

    If `capture` is true, return the command's output as bytes; otherwise return None."""
    # check=True raises an error if the command exits with a failure code.
    return subprocess.run([str(arg) for arg in args], cwd=cwd, check=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def main():
    """Check prerequisites and the pinned source, apply the patch, then configure and build the server."""
    # ---------------- Command-line options ----------------
    # Use this file's docstring as the help text.
    parser = argparse.ArgumentParser(description=__doc__)
    # --source is where the ds3os checkout lives; --build is where build output goes; --jobs is how many compile jobs run in parallel.
    parser.add_argument("--source", type=Path, default=ROOT / "vendor/ds3os")
    parser.add_argument("--build", type=Path, default=ROOT / "build/ds3os")
    parser.add_argument("--jobs", type=int, default=4)
    # Read the options the user typed.
    args = parser.parse_args()
    # Sanity check: at least one job is needed.
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    # Make sure the needed programs (git, cmake, C and C++ compilers) are installed.
    for tool in ("git", "cmake", "cc", "c++"):
        if not shutil.which(tool):
            parser.error(f"Install the build prerequisite: {tool}")
    # Turn the folder options into absolute paths.
    source, build = args.source.resolve(), args.build.resolve()
    # upstream.lock.json pins the exact upstream repository, commit and patch checksum.
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    # The patch file this project applies on top of upstream.
    patch = ROOT / "patches/ds3os-linux-development.patch"
    # Refuse to continue if the patch changed from what the lock file recorded.
    if hashlib.sha256(patch.read_bytes()).hexdigest() != lock["patch_sha256"]:
        parser.error("Patch differs from upstream.lock.json; review the change first")
    # First run: download only the pinned commit into a new Git checkout.
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "init", source)
        run("git", "remote", "add", "origin", lock["repository"], cwd=source)
        run("git", "fetch", "--depth", "1", "origin", lock["commit"], cwd=source)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=source)
    # An existing folder that is not a Git checkout is left alone rather than overwritten.
    if not (source / ".git").exists():
        parser.error("Source directory exists but is not a Git checkout; preserved")
    # The checkout must be at exactly the pinned commit.
    head = run("git", "rev-parse", "HEAD", cwd=source, capture=True).decode().strip()
    if head != lock["commit"]:
        parser.error("Source HEAD differs from the pinned commit; checkout preserved")
    # Staged changes are not expected here; stop and preserve them.
    if run("git", "diff", "--cached", "--binary", cwd=source, capture=True):
        parser.error("Source contains staged changes; preserved")
    # Look at the unstaged changes in the checkout.
    diff = run("git", "diff", "--binary", "--no-ext-diff", cwd=source, capture=True)
    # No changes yet: test that the patch applies cleanly, then apply it.
    if not diff:
        run("git", "apply", "--check", patch, cwd=source)
        run("git", "apply", patch, cwd=source)
    # Changes already exist: they must be exactly this patch, otherwise stop to protect the user's work.
    elif diff != patch.read_bytes():
        parser.error("Source contains changes beyond the supplied patch; preserved")
    # Configure the build in Release mode, with the option that makes the server listen only on localhost.
    run("cmake", "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
        "-DWYLD_LOOPBACK_ONLY=ON")
    # Compile just the "Server" target using the requested number of parallel jobs.
    run("cmake", "--build", build, "--target", "Server", "--parallel", args.jobs)
    # Tell the user where the built program is and what it is (and is not).
    print(f"Native server: {source / 'bin/x64_release/Server'}")
    print("Development infrastructure only. No seamless game adapter is installed.")


# Run main() only when this file is started directly.
if __name__ == "__main__":
    main()
