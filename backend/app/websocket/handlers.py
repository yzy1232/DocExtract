"""
WebSocket 路由处理器
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.websocket.manager import manager
from app.core.security import decode_token

ws_router = APIRouter(tags=["WebSocket"])


async def _authenticate_ws(token: str) -> str:
    """WebSocket JWT 认证，返回 user_id"""
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id or payload.get("type") != "access":
        return None
    return user_id


@ws_router.websocket("/ws/processing-status/{task_id}")
async def ws_processing_status(
    websocket: WebSocket,
    task_id: str,
    token: str = Query(description="JWT访问令牌"),
):
    """
    订阅提取任务实时状态推送
    前端通过此端点获取任务进度更新
    """
    user_id = await _authenticate_ws(token)
    if not user_id:
        await websocket.close(code=4001, reason="认证失败")
        return

    room_id = f"task:{task_id}"
    await manager.connect(websocket, room_id)
    try:
        # 立即推送当前进度
        await _push_current_progress(websocket, task_id)

        while True:
            # 保持连接，等待客户端 ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)


@ws_router.websocket("/ws/upload-progress/{task_id}")
async def ws_upload_progress(
    websocket: WebSocket,
    task_id: str,
    token: str = Query(description="JWT访问令牌"),
):
    """订阅文档上传进度"""
    user_id = await _authenticate_ws(token)
    if not user_id:
        await websocket.close(code=4001, reason="认证失败")
        return

    room_id = f"upload:{task_id}"
    await manager.connect(websocket, room_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)


@ws_router.websocket("/ws/notifications/{user_id}")
async def ws_user_notifications(
    websocket: WebSocket,
    user_id: str,
    token: str = Query(description="JWT访问令牌"),
):
    """订阅用户系统通知"""
    token_user_id = await _authenticate_ws(token)
    if not token_user_id or token_user_id != user_id:
        await websocket.close(code=4001, reason="认证失败")
        return

    room_id = f"user:{user_id}"
    await manager.connect(websocket, room_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)


async def _push_current_progress(websocket: WebSocket, task_id: str):
    """推送当前任务进度快照"""
    try:
        from app.core.cache import get_cache_manager
        cache = await get_cache_manager()
        progress = await cache.get_progress(task_id)
        if progress:
            import json
            await websocket.send_text(json.dumps({
                "type": "progress",
                "task_id": task_id,
                **progress,
            }))
    except Exception:
        pass


async def notify_task_progress(task_id: str, progress: float, message: str = ""):
    """供内部调用：推送任务进度更新"""
    await manager.send_to_room(f"task:{task_id}", {
        "type": "progress",
        "task_id": task_id,
        "progress": progress,
        "message": message,
    })


async def notify_task_completed(task_id: str, success: bool):
    """供内部调用：推送任务完成通知"""
    await manager.send_to_room(f"task:{task_id}", {
        "type": "completed",
        "task_id": task_id,
        "success": success,
    })
