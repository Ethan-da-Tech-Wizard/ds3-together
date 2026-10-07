#!/usr/bin/env python3
"""Build the pinned ds3os native development server, bound to localhost."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=None, capture=False):
    return subprocess.run([str(arg) for arg in args], cwd=cwd, check=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "vendor/ds3os")
    parser.add_argument("--build", type=Path, default=ROOT / "build/ds3os")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    for tool in ("git", "cmake", "cc", "c++"):
        if not shutil.which(tool):
            parser.error(f"Install the build prerequisite: {tool}")
    source, build = args.source.resolve(), args.build.resolve()
    lock = json.loads((ROOT / "upstream.lock.json").read_text())
    patch = ROOT / "patches/ds3os-linux-development.patch"
    if hashlib.sha256(patch.read_bytes()).hexdigest() != lock["patch_sha256"]:
        parser.error("Patch differs from upstream.lock.json; review the change first")
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "init", source)
        run("git", "remote", "add", "origin", lock["repository"], cwd=source)
        run("git", "fetch", "--depth", "1", "origin", lock["commit"], cwd=source)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=source)
    if not (source / ".git").exists():
        parser.error("Source directory exists but is not a Git checkout; preserved")
    head = run("git", "rev-parse", "HEAD", cwd=source, capture=True).decode().strip()
    if head != lock["commit"]:
        parser.error("Source HEAD differs from the pinned commit; checkout preserved")
    if run("git", "diff", "--cached", "--binary", cwd=source, capture=True):
        parser.error("Source contains staged changes; preserved")
    diff = run("git", "diff", "--binary", "--no-ext-diff", cwd=source, capture=True)
    if not diff:
        run("git", "apply", "--check", patch, cwd=source)
        run("git", "apply", patch, cwd=source)
    elif diff != patch.read_bytes():
        parser.error("Source contains changes beyond the supplied patch; preserved")
    run("cmake", "-S", source, "-B", build, "-DCMAKE_BUILD_TYPE=Release",
        "-DWYLD_LOOPBACK_ONLY=ON")
    run("cmake", "--build", build, "--target", "Server", "--parallel", args.jobs)
    print(f"Native server: {source / 'bin/x64_release/Server'}")
    print("Development infrastructure only. No seamless game adapter is installed.")


if __name__ == "__main__":
    main()
