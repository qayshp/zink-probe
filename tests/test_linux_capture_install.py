"""Capture service planning and fail-closed installation; no system changes."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "install_linux_capture",
    Path(__file__).resolve().parents[1] / "native/install_linux_capture.py",
)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_plan_is_capture_only_and_separates_profiles(tmp_path):
    plans = [
        installer.plan(
            tmp_path / "binary", tmp_path / "venv/python", tmp_path, mode, port
        )
        for mode, port in (("fill", 8631), ("preserve-edges", 8632))
    ]
    assert not list(tmp_path.iterdir())
    assert plans[0][0] != plans[1][0] and plans[0][1] != plans[1][1]
    for root, name, unit, register in plans:
        assert "capture" in name and root.name.endswith("capture")
        assert "NoNewPrivileges=yes" in unit
        assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in unit
        assert "AF_BLUETOOTH" not in unit
        assert "printer-error-policy=abort-job" in register
        assert "printer-is-shared=false" in register
        assert "-d" not in register  # no change to default printer


def test_service_argument_escaping_preserves_literal_paths():
    assert installer.unit_quote('/a %n/$HOME/"x"') == '"/a %%n/$$HOME/\\"x\\""'
    with pytest.raises(ValueError, match="control"):
        installer.unit_quote("/tmp/path\nExecStart=bad")


@pytest.mark.parametrize("layout,port", [("live", 8632), ("fill", 0), ("fill", 65536)])
def test_invalid_plan_rejected(tmp_path, layout, port):
    with pytest.raises(ValueError):
        installer.plan(tmp_path / "binary", tmp_path / "python", tmp_path, layout, port)
    assert not list(tmp_path.iterdir())


def test_existing_capture_data_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(installer.sys, "platform", "linux")
    data = tmp_path / "preserve-edges-capture"
    data.mkdir()
    marker = data / "config.json"
    marker.write_text("keep existing data")
    monkeypatch.setattr(
        installer.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("No process should run"),
    )
    with pytest.raises(ValueError, match="already exists"):
        installer.install(
            tmp_path / "binary",
            tmp_path / "python",
            tmp_path,
            "preserve-edges",
            8632,
            tmp_path / "units",
        )
    assert marker.read_text() == "keep existing data"


@pytest.mark.parametrize(
    "extra", [{"mode": "live"}, {"mode": "capture", "address": "00:11:22:33:44:55"}]
)
def test_validator_refuses_hardware_even_with_optimized_python(tmp_path, extra):
    (tmp_path / "config.json").write_text(
        json.dumps({"data_dir": str(tmp_path), **extra})
    )
    result = subprocess.run(
        [
            sys.executable,
            "-O",
            str(
                Path(__file__).resolve().parents[1] / "native/validate_linux_capture.py"
            ),
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Requires capture mode" in result.stderr
    assert not (tmp_path / "output").exists()
