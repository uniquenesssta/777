"""Cooperative turns for Windows background reads, never for writer lanes.

Only loops we own have checkpoints. Native decode/GC and OS scheduling can
still exceed this budget; it is not a hard latency bound or an I/O timeout.
"""
from contextlib import contextmanager
import sys
from threading import local
import time

WINDOWS = sys.platform == 'win32'
TURN_SECONDS = .008
PAUSE_SECONDS = .001
_state = local()


class ReadTurn:
    def __init__(self):
        self.deadline = time.perf_counter() + TURN_SECONDS

    def checkpoint(self):
        if time.perf_counter() >= self.deadline:
            self.pause()
            # Start the next budget after waking, including any OS delay.
            self.deadline = time.perf_counter() + TURN_SECONDS

    def pause(self):
        time.sleep(PAUSE_SECONDS)


@contextmanager
def read_turns():
    previous = getattr(_state, 'turn', None)
    _state.turn = previous or (ReadTurn() if WINDOWS else None)
    try:
        yield
    finally:
        _state.turn = previous


def checkpoint():
    turn = getattr(_state, 'turn', None)
    if turn is not None:
        turn.checkpoint()
