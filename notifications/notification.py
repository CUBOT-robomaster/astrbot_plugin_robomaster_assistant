from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from astrbot.api.event import MessageChain
import astrbot.api.message_components as Comp


@dataclass
class SlidingWindowCounter:
    window_seconds: int
    timestamps: list[float] = field(default_factory=list)

    def increment(self) -> int:
        now = time.time()
        min_time = now - self.window_seconds
        self.timestamps = [ts for ts in self.timestamps if ts >= min_time]
        self.timestamps.append(now)
        return len(self.timestamps)


class CircuitBreaker:
    def __init__(self, recover_at: float = 0.0):
        self.windows = [
            ("每5秒", SlidingWindowCounter(5), 3),
            ("每分钟", SlidingWindowCounter(60), 5),
            ("每小时", SlidingWindowCounter(3600), 15),
        ]
        self.recover_at = float(recover_at or 0)

    def allow(self) -> tuple[bool, str]:
        now = time.time()
        if now < self.recover_at:
            return False, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.recover_at))
        if self.recover_at:
            self.recover_at = 0.0
            for _, counter, _ in self.windows:
                counter.timestamps.clear()
        for name, counter, max_count in self.windows:
            count = counter.increment()
            if count > max_count:
                self.recover_at = now + 12 * 3600
                recover = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.recover_at))
                return False, f"{name}发送数量达到 {count}，超过最大限制 {max_count}，已熔断到 {recover}"
        return True, ""

    def recovery_timestamp(self) -> float:
        return self.recover_at


def plain_chain(text: str) -> Any:
    return MessageChain([Comp.Plain(text)])
