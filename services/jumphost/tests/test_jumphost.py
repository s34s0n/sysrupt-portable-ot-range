"""Tests for Jump Host files."""
import os
import pytest

BASE = os.path.join(os.path.dirname(__file__), "..")


def test_bash_history_exists():
    path = os.path.join(BASE, "bash_history")
    assert os.path.exists(path)
    with open(path) as f:
        content = f.read()
    assert "openplc@10.0.3.20" in content
    assert "10.0.4.101" in content
    assert "snap7" in content


def test_hosts_file_exists():
    path = os.path.join(BASE, "hosts")
    assert os.path.exists(path)
    with open(path) as f:
        content = f.read()
    assert "scada-hmi" in content
    assert "plc-intake" in content
    assert "safety-plc" in content
    assert "10.0.5.201" in content


def test_setup_script_exists():
    path = os.path.join(BASE, "setup.sh")
    assert os.path.exists(path)
    assert os.access(path, os.X_OK)


def test_config_exists():
    path = os.path.join(BASE, "config.yml")
    assert os.path.exists(path)
    with open(path) as f:
        content = f.read()
    assert "jumphost" in content
    assert "maintenance" in content
