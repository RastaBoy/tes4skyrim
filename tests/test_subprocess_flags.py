"""`std_handles()` -- the pythonw.exe grandchild blindness.

A GUI-launched build runs as `pythonw.exe`, whose std handles are NOT
inheritable. A child spawned without explicitly named handles therefore starts
with `sys.stdout is None`: `print` silently drops every line, and any attribute
read off the stream (`sys.stdout.encoding`) raises AttributeError. That is what
made the ship patch fail from the GUI with an empty log.
"""
import os
import subprocess
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from subprocess_flags import std_handles  # noqa: E402


def test_returns_descriptors_for_real_streams(tmp_path):
    """A process with genuine pipes hands both descriptors down."""
    script = tmp_path / "probe.py"
    script.write_text(textwrap.dedent("""
        import sys, os
        sys.path.insert(0, sys.argv[1])
        from subprocess_flags import std_handles
        h = std_handles()
        assert h == {'stdout': 1, 'stderr': 2}, h
        print('ok')
    """), encoding="utf-8")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-u", str(script), repo],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"


def test_absent_streams_are_skipped(monkeypatch):
    """`sys.stdout is None` is exactly the case this exists for: no key, no
    AttributeError, and the caller falls back to plain inheritance."""
    monkeypatch.setattr(sys, "stdout", None)
    assert "stdout" not in std_handles()


def test_a_stream_without_a_descriptor_is_skipped(monkeypatch):
    """pytest's own capture has no fileno; asking must not raise."""
    import io
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    assert "stdout" not in std_handles()


@pytest.mark.skipif(sys.platform != "win32", reason="pythonw.exe is Windows")
def test_a_pythonw_grandchild_can_still_speak(tmp_path):
    """The end-to-end defect: pythonw -> child -> grandchild.

    Without `std_handles()` the grandchild's print vanishes and its
    `sys.stdout.encoding` raises. With it, both work.
    """
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pytest.skip("no pythonw.exe next to this interpreter")

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    grandchild = tmp_path / "grandchild.py"
    grandchild.write_text(
        "import sys\n"
        "print('encoding is', sys.stdout.encoding)\n", encoding="utf-8")

    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent(f"""
        import subprocess, sys
        sys.path.insert(0, {repo!r})
        from subprocess_flags import POPEN_FLAGS, std_handles
        r = subprocess.run([sys.executable, '-u', {str(grandchild)!r}],
                           **std_handles(), **POPEN_FLAGS)
        print('grandchild rc', r.returncode)
    """), encoding="utf-8")

    out = subprocess.run([pythonw, "-u", str(child)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "encoding is" in out.stdout, out.stdout
    assert "grandchild rc 0" in out.stdout, out.stdout
