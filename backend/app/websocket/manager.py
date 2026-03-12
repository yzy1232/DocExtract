"""
WebSocket 连接管理器
"""
import json
from typing import Dict, Set
from fastapi import WebSocket


class ConnectionManager:
    """管理多个 WebSocket 连接，支持按房间（task_id / user_id）分组推送"""

    def __init__(self):
        # room_id -> {websocket}
        self._rooms: Dict[str, Set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()
        if room_id not in self._rooms:
            self._rooms[room_id] = set()
        self._rooms[room_id].add(websocket)

    def disconnect(self, websocket: WebSocket, room_id: str):
        room = self._rooms.get(room_id, set())
        room.discard(websocket)
        if not room:
            self._rooms.pop(room_id, None)

    async def send_to_room(self, room_id: str, message: dict):
        """向指定房间的所有连接推送消息"""
        room = self._rooms.get(room_id, set())
        dead = set()
        for ws in room:
            try:
                await ws.send_text(json.dumps(message, ensure_ascii=False, default=str))
            except Exception:
                dead.add(ws)
        for ws in dead:
            room.discard(ws)

    async def broadcast(self, message: dict):
        """全局广播"""
        for room_id in list(self._rooms.keys()):
            await self.send_to_room(room_id, message)

    @property
    def total_connections(self) -> int:
        return sum(len(s) for s in self._rooms.values())


# 全局连接管理器实例
manager = ConnectionManager()
