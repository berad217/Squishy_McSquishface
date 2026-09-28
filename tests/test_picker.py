"""The picker's failure paths (the happy path opens a real window; see the DEVLOG spike)."""

import pytest

from squishy.picker import PickerError, pick


def test_python_without_tk_is_explained(tmp_path, monkeypatch):
    # A stand-in tkinter that fails to import, as on a Python installed without Tcl/Tk.
    (tmp_path / "tkinter").mkdir()
    (tmp_path / "tkinter" / "__init__.py").write_text("raise ImportError(\"No module named '_tkinter'\")")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    with pytest.raises(PickerError, match="no Tk"):
        pick("folder")


def test_unknown_mode():
    with pytest.raises(ValueError):
        pick("desktop")
