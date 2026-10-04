import io
import time

from harness_cli.render import Renderer, Spinner
from harnessy.types import ToolCall, ToolResult


class TTY(io.StringIO):
    def isatty(self):
        return True


def wait_for(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


def test_draws_after_delay_and_erases_on_stop():
    out = TTY()
    s = Spinner(out, enabled=True, delay=0.01, interval=0.01)
    s.start("Running…")
    assert wait_for(lambda: "Running…" in out.getvalue())
    s.stop()
    text = out.getvalue()
    assert text.endswith("\r\033[2K")  # the line is erased
    assert "Ctrl-C to interrupt" in text and "0s" in text


def test_fast_work_draws_nothing():
    out = TTY()
    s = Spinner(out, enabled=True, delay=0.5, interval=0.01)
    s.start("Running…")
    s.stop()
    assert out.getvalue() == ""


def test_disabled_draws_nothing():
    out = TTY()
    s = Spinner(out, enabled=False, delay=0.0, interval=0.01)
    s.start("Running…")
    time.sleep(0.05)
    s.stop()
    assert out.getvalue() == ""


def test_elapsed_seconds_shown():
    out = TTY()
    now = [100.0]
    s = Spinner(out, enabled=True, delay=0.0, interval=0.01, clock=lambda: now[0])
    s.start("Thinking…")
    now[0] = 112.4
    assert wait_for(lambda: "Thinking… 12s" in out.getvalue())
    s.stop()


def test_renderer_output_stops_spinner_first():
    out = TTY()
    r = Renderer(out, color=False)
    r.spinner = Spinner(out, enabled=True, delay=0.0, interval=0.01)
    call = ToolCall("1", "run_shell", {"command": "sleep 3"})
    r.tool_start(call)
    r.busy_for(call)
    assert wait_for(lambda: "Running…" in out.getvalue())
    r.tool_end(call, ToolResult("1", "exit code 0"))
    assert not r.spinner.active
    after_erase = out.getvalue().rsplit("\033[2K", 1)[1]
    assert after_erase == "  ⎿ exit code 0\n"


def test_not_a_terminal_means_no_spinner():
    r = Renderer(io.StringIO())
    assert r.spinner.enabled is False
