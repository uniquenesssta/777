"""Bounded daemon I/O lanes. Only the owner drains events; workers never use Tk."""
from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass, field
from queue import SimpleQueue
from threading import Condition, Event, Thread
import time

from quote_files.scheduling import read_turns


class Cancelled(Exception):
    pass


class QueueFull(Exception):
    pass


@dataclass
class Task:
    number: int
    channel: str
    write: bool
    action: object = field(repr=False)
    deadline: float = 0
    cancelled: Event = field(default_factory=Event, repr=False)
    state: str = "queued"
    timeout_reported: bool = False


class Context:
    def __init__(self, task, events):
        self.task, self.events = task, events

    def check(self):
        if not self.task.write and self.task.cancelled.is_set():
            raise Cancelled()

    def progress(self, value):
        self.events.put((self.task, "progress", value))


class Jobs:
    def __init__(self, *, readers=2, capacity=4, timeout=30):
        self.capacity, self.timeout = capacity, timeout
        self.events = SimpleQueue()
        self.condition = Condition()
        self.reads, self.writes = deque(), deque()
        self.tasks, self.latest = {}, {}
        self.closed, self.sequence = False, 0
        self._workers = []
        for lane in [False] * readers + [True]:
            worker = Thread(target=self._worker, args=(lane,), daemon=True, name="777-write" if lane else "777-read")
            self._workers.append(worker)
            worker.start()

    def submit(self, channel, action, *, write=False):
        with self.condition:
            if self.closed:
                raise QueueFull("窗口正在关闭")
            if write and any(t.write and t.state in {"queued", "running"} for t in self.tasks.values()):
                raise QueueFull("已有写入进行中；请等待结果，不重复提交")
            old = self.latest.get(channel)
            if old and not old.write:
                old.cancelled.set()
                if old.state == "queued":
                    self.reads.remove(old)
                    old.state = "cancelled"
                    self.tasks.pop(old.number, None)
            if not write and len(self.reads) >= self.capacity:
                raise QueueFull("读取队列已满；正在进行的I/O尚未结束")
            self.sequence += 1
            task = Task(self.sequence, channel, write, action, time.monotonic() + self.timeout)
            self.tasks[task.number] = self.latest[channel] = task
            (self.writes if write else self.reads).append(task)
            self.condition.notify_all()
            return task

    def _worker(self, write):
        lane = self.writes if write else self.reads
        while True:
            with self.condition:
                self.condition.wait_for(lambda: lane or self.closed)
                if not lane:
                    return
                task = lane.popleft()
                task.state = "running"
            context = Context(task, self.events)
            try:
                context.check()
                with nullcontext() if write else read_turns():
                    value = task.action(context)
                context.check()
                state = "completed"
            except Cancelled:
                state, value = "cancelled", None
            except Exception as exc:
                state, value = "failed", exc
            with self.condition:
                task.state = state
            self.events.put((task, state, value))

    def drain(self):
        events = []
        with self.condition:
            for task in tuple(self.tasks.values()):
                if task.state in {"queued", "running"} and not task.timeout_reported and time.monotonic() >= task.deadline:
                    task.timeout_reported = True
                    if not task.write:
                        task.cancelled.set()
                        if task.state == "queued":
                            self.reads.remove(task)
                            task.state = "cancelled"
                            self.tasks.pop(task.number, None)
                    events.append((task, "timeout", None))
        while not self.events.empty():
            event = self.events.get()
            events.append(event)
            if event[1] in {"completed", "failed", "cancelled"}:
                with self.condition:
                    self.tasks.pop(event[0].number, None)
        return events

    def current(self, task):
        return self.latest.get(task.channel) is task and (task.write or not task.cancelled.is_set())

    @property
    def writing(self):
        with self.condition:
            return any(t.write for t in self.tasks.values())

    def cancel_reads(self):
        with self.condition:
            for task in tuple(self.tasks.values()):
                if not task.write:
                    task.cancelled.set()
                    if task.state == "queued":
                        self.tasks.pop(task.number, None)
                        task.state = "cancelled"
            self.reads.clear()

    def close(self):
        self.cancel_reads()
        with self.condition:
            if self.writing:
                raise RuntimeError("不能丢弃尚未交付结果的写任务")
            self.closed = True
            self.condition.notify_all()

    def wait_closed(self, timeout):
        """Diagnostic teardown only: wait for native I/O before deleting its sandbox.

        Window close remains nonblocking. A timeout does not terminate workers
        or authorize deleting files they may still be using.
        """
        with self.condition:
            if not self.closed:
                raise RuntimeError("必须先关闭任务队列，再等待诊断线程退出")
        deadline = time.monotonic() + timeout
        for worker in self._workers:
            worker.join(max(0, deadline - time.monotonic()))
        return all(not worker.is_alive() for worker in self._workers)
