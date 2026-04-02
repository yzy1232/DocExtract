"""
Celery worker 进程级事件循环管理。

同一进程内的异步任务应复用同一个 event loop，避免 async 资源
（如 aiomysql 连接）在不同 loop 间复用导致 RuntimeError。
"""
import asyncio
import os


_worker_loop = None
_worker_loop_pid = None


def get_worker_loop() -> asyncio.AbstractEventLoop:
    """获取当前进程绑定的 worker event loop。"""
    global _worker_loop, _worker_loop_pid

    current_pid = os.getpid()
    if _worker_loop is None or _worker_loop.is_closed() or _worker_loop_pid != current_pid:
        _worker_loop = asyncio.new_event_loop()
        _worker_loop_pid = current_pid

    return _worker_loop
