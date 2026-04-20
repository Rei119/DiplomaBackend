"""
WebSocket signaling server for WebRTC-based live monitoring.
Routes WebRTC offer/answer/ICE between students and the watching teacher,
and forwards real-time flag events (tab-switch, look-down) to the teacher.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from typing import Dict, Optional

from ..database import SessionLocal
from ..config import settings
from .. import models

router = APIRouter(tags=["monitor"])


# ── In-memory room store ──────────────────────────────────────────────────────

class Room:
    def __init__(self):
        self.teacher: Optional[WebSocket] = None
        self.students: Dict[str, WebSocket] = {}   # session_id → ws
        self.info:     Dict[str, dict]     = {}    # session_id → {name, flag_count, flags[]}

_rooms: Dict[str, Room] = {}   # exam_code (upper) → Room

def _get_room(code: str) -> Room:
    code = code.upper()
    if code not in _rooms:
        _rooms[code] = Room()
    return _rooms[code]


# ── JWT helper ────────────────────────────────────────────────────────────────

def _user_from_token(token: str) -> Optional[models.User]:
    db: Session = SessionLocal()
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub", "")
        if not username:
            return None
        return db.query(models.User).filter(models.User.username == username).first()
    except JWTError:
        return None
    finally:
        db.close()


# ── Safe send helper ──────────────────────────────────────────────────────────

async def _send(ws: WebSocket, data: dict):
    try:
        await ws.send_json(data)
    except Exception:
        pass


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws/monitor/{exam_code}")
async def monitor_ws(
    websocket: WebSocket,
    exam_code: str,
    token: str = Query(...),
):
    user = _user_from_token(token)
    if not user:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    room = _get_room(exam_code)
    role:       Optional[str] = None
    session_id: Optional[str] = None

    try:
        while True:
            msg: dict = await websocket.receive_json()
            mtype: str = msg.get("type", "")

            # ── register ──────────────────────────────────────────────────────
            if mtype == "register":
                role = msg.get("role")

                if role == "teacher":
                    room.teacher = websocket
                    # Send snapshot of already-connected students
                    await _send(websocket, {
                        "type": "students_list",
                        "students": list(room.info.values()),
                    })
                    # Ask existing students to (re-)send their offer
                    for sw in room.students.values():
                        await _send(sw, {"type": "request_offer"})

                elif role == "student":
                    session_id = msg.get("session_id")
                    name = msg.get("name") or user.username or "Student"
                    room.students[session_id] = websocket
                    room.info[session_id] = {
                        "session_id": session_id,
                        "name": name,
                        "flag_count": 0,
                        "flags": [],
                    }
                    # Notify teacher a new student joined
                    if room.teacher:
                        await _send(room.teacher, {
                            "type": "student_joined",
                            "session_id": session_id,
                            "name": name,
                        })
                        # Ask student to start streaming now
                        await _send(websocket, {"type": "request_offer"})

            # ── WebRTC: student → teacher ─────────────────────────────────────
            elif mtype == "offer" and role == "student" and session_id:
                if room.teacher:
                    await _send(room.teacher, {
                        "type": "offer",
                        "session_id": session_id,
                        "sdp": msg.get("sdp"),
                    })

            # ── WebRTC: teacher → student ─────────────────────────────────────
            elif mtype == "answer" and role == "teacher":
                target = msg.get("session_id")
                if target and target in room.students:
                    await _send(room.students[target], {
                        "type": "answer",
                        "sdp": msg.get("sdp"),
                    })

            # ── ICE candidates (bidirectional) ────────────────────────────────
            elif mtype == "ice":
                if role == "student" and session_id and room.teacher:
                    await _send(room.teacher, {
                        "type": "ice",
                        "session_id": session_id,
                        "candidate": msg.get("candidate"),
                    })
                elif role == "teacher":
                    target = msg.get("session_id")
                    if target and target in room.students:
                        await _send(room.students[target], {
                            "type": "ice",
                            "candidate": msg.get("candidate"),
                        })

            # ── Real-time flag events ─────────────────────────────────────────
            elif mtype == "flag" and role == "student" and session_id:
                flag_type = msg.get("flag_type", "unknown")
                count     = int(msg.get("count", 0))
                ts        = msg.get("timestamp", 0)

                if session_id in room.info:
                    room.info[session_id]["flag_count"] = count
                    room.info[session_id]["flags"].append({
                        "type": flag_type,
                        "timestamp": ts,
                    })

                if room.teacher:
                    await _send(room.teacher, {
                        "type": "flag",
                        "session_id": session_id,
                        "flag_type":  flag_type,
                        "count":      count,
                        "timestamp":  ts,
                    })

    except WebSocketDisconnect:
        if role == "teacher":
            room.teacher = None
        elif role == "student" and session_id:
            room.students.pop(session_id, None)
            room.info.pop(session_id, None)
            if room.teacher:
                await _send(room.teacher, {
                    "type": "student_left",
                    "session_id": session_id,
                })
