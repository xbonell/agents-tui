"""Drives the real TUI in a pseudo-terminal."""

import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def drive(keys, cols=100, rows=40, extra=()):
  import fcntl
  import termios

  with tempfile.TemporaryDirectory() as tmp:
    argv = [sys.executable, str(ROOT / "bin" / "agents-tui"), "--usage-dir", str(FIXTURES), "--no-collect",
            "--config", os.path.join(tmp, "config.toml"), *extra]
    pid, fd = pty.fork()
    if pid == 0:
      os.environ.update({"TERM": "xterm-256color", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                         "XDG_STATE_HOME": tmp, "HOME": tmp})
      os.execv(argv[0], argv)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    out = b""

    def pump(seconds):
      nonlocal out
      end = time.time() + seconds
      while time.time() < end:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
          try:
            out += os.read(fd, 65536)
          except OSError:
            return

    pump(1.0)
    for key in keys:
      os.write(fd, key)
      pump(0.4)
    deadline = time.time() + 5
    while time.time() < deadline:
      done, status = os.waitpid(pid, os.WNOHANG)
      if done:
        os.close(fd)
        return out, os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
      pump(0.1)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    return out, None


class TuiTests(unittest.TestCase):
  def test_draws_and_quits(self):
    out, code = drive([b"j", b"\r", b"?", b"\x1b", b"s", b"j", b" ", b"\x1b", b"e", b"q"])
    self.assertEqual(code, 0)
    text = out.decode("utf-8", "replace")
    for expected in ("Claude Code", "Sign-in required", "Settings", "Providers", "Show or hide"):
      self.assertIn(expected, text)

  def test_small_and_ascii_terminals(self):
    for cols, rows, extra in ((30, 8, ()), (80, 24, ("--ascii", "--no-color"))):
      out, code = drive([b"G", b"\x1b[6~", b"q"], cols=cols, rows=rows, extra=extra)
      self.assertEqual(code, 0, (cols, rows))

  def test_not_a_terminal(self):
    done = subprocess.run([sys.executable, str(ROOT / "bin" / "agents-tui"), "--no-collect"],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True)
    self.assertEqual(done.returncode, 2)
    self.assertIn("agents-tui print", done.stderr)


if __name__ == "__main__":
  unittest.main()
