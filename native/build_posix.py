"""Build a private macOS/Linux PAPPL bridge from pinned source snapshots.

No system CUPS replacement, service installation, queue registration or Bluetooth.
Source repositories are read through git archive; their working trees are untouched.
"""

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
from pathlib import Path

from patch_pappl import patch

PAPPL_REV = "02050bdbd4b3e610180c0433f47b7bf2c4569e44"
CUPS_REV = "f7888eacb576dc13d954c11d0af57af71af3d4a9"  # libcups v3.0.3


def snapshot(repository, revision, destination):
    destination.mkdir()
    archive = subprocess.run(
        ["git", "-C", str(repository), "archive", revision],
        check=True,
        capture_output=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(destination)], input=archive, check=True)


def build(pappl, cups, output):
    if platform.system() not in ("Darwin", "Linux"):
        raise ValueError("This builder supports macOS and Linux")
    output = output.resolve()
    # Upstream make/configure do not reliably quote paths with spaces/metacharacters.
    if any(c.isspace() or c in "'\"$`\\;#" for c in str(output)):
        raise ValueError(
            "Build output path must not contain spaces or shell metacharacters"
        )
    for tool in ("git", "tar", "make", "cc", "pkg-config"):
        if not shutil.which(tool):
            raise ValueError(f"Required build tool missing: {tool}")
    output.mkdir(parents=True)  # No overwrite/reuse of a possibly patched source tree.
    prefix = output / "prefix"
    prefix.mkdir()
    source = output / "pappl-src"
    cups_source = output / "cups-src"
    snapshot(pappl, PAPPL_REV, source)
    snapshot(cups, CUPS_REV, cups_source)
    patch(source)
    env = os.environ.copy()
    if platform.system() == "Darwin":
        # Upstream defaults to a universal binary, but Homebrew dependencies are
        # native to this machine. Build one matching architecture explicitly.
        env["OPTIM"] = f"-O2 -arch {platform.machine()}"
        if shutil.which("brew"):
            openssl = subprocess.check_output(
                ["brew", "--prefix", "openssl@3"], text=True
            ).strip()
            env["PKG_CONFIG_PATH"] = (
                f"{openssl}/lib/pkgconfig" + os.pathsep + env.get("PKG_CONFIG_PATH", "")
            )
    env["PKG_CONFIG_PATH"] = (
        str(prefix / "lib/pkgconfig") + os.pathsep + env.get("PKG_CONFIG_PATH", "")
    )
    jobs = str(min(os.cpu_count() or 2, 8))
    with (output / "build.log").open("w") as log:

        def run(args, cwd):
            log.write(shlex.join(map(str, args)) + "\n")
            log.flush()
            subprocess.run(
                list(map(str, args)),
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )

        run(
            [
                "./configure",
                f"--prefix={prefix}",
                f"--libdir={prefix / 'lib'}",
                "--disable-shared",
                "--disable-dbus",
                "--with-tls=openssl",
            ],
            cups_source,
        )
        run(["make", "-C", "cups", f"-j{jobs}"], cups_source)
        run(["make", "-C", "cups", "install"], cups_source)
        pc = prefix / "lib/pkgconfig"
        pc.mkdir(exist_ok=True)
        shutil.copyfile(cups_source / "cups3.pc", pc / "cups3.pc")
        run(
            [
                "./configure",
                f"--prefix={prefix}",
                f"--libdir={prefix / 'lib'}",
                "--disable-shared",
                "--disable-libpam",
                "--disable-libusb",
                "--enable-libjpeg",
                "--enable-libpng",
            ],
            source,
        )
        run(["make", "-C", "pappl", f"-j{jobs}"], source)
        run(["make", "-C", "pappl", "install"], source)
        flags = subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "--static", "pappl2"],
            env=env,
            text=True,
        )
        binary = output / "zink-ipp"
        run(
            [
                "cc",
                "-std=c11",
                "-D_POSIX_C_SOURCE=200809L",
                "-D_DARWIN_C_SOURCE",
                "-D_DEFAULT_SOURCE",
                "-Wall",
                "-Wextra",
                "-O2",
                Path(__file__).with_name("select-app.c").resolve(),
                "-o",
                binary,
                *shlex.split(flags),
            ],
            output,
        )
        run([binary, "--version"], output)
    licenses = output / "licenses"
    licenses.mkdir()
    for name, repo in (("PAPPL", source), ("LIBCUPS", cups_source)):
        for filename in ("LICENSE", "NOTICE"):
            if (repo / filename).exists():
                shutil.copyfile(repo / filename, licenses / f"{name}-{filename}.txt")
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "LICENSE",
        licenses / "ZINK-PROBE-LICENSE.txt",
    )
    info = {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "pappl_revision": PAPPL_REV,
        "libcups_revision": CUPS_REV,
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "linking": "static PAPPL/libcups; system/package-manager image, TLS and OS libraries",
        "system_cups_modified": False,
        "queue_installed": False,
    }
    (output / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    print(json.dumps(info))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pappl-source", type=Path, required=True)
    parser.add_argument("--cups-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.pappl_source, args.cups_source, args.output)
