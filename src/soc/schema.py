"""EDR 텔레메트리와 알림 스키마 (ECS를 단순화한 형태).

이벤트 종류(type):
  process  : 프로세스 생성 (pid, ppid, 이름, 명령줄, 부모, 서명 여부)
  script   : PowerShell 스크립트 블록 로깅 내용
  network  : 네트워크 연결
  file     : 파일 생성/수정/이름변경/삭제
  registry : 레지스트리 값 설정
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ProcessInfo(BaseModel):
    pid: int
    ppid: int | None = None
    name: str
    cmdline: str = ""
    parent_name: str | None = None
    signed: bool = True
    user: str | None = None


class NetworkInfo(BaseModel):
    dst_ip: str
    dst_port: int
    proto: str = "tcp"
    bytes_out: int = 0


class FileInfo(BaseModel):
    path: str
    action: Literal["create", "modify", "rename", "delete"]
    new_path: str | None = None


class RegistryInfo(BaseModel):
    key: str
    value: str


class Event(BaseModel):
    event_id: str
    ts: datetime
    host: str
    type: Literal["process", "script", "network", "file", "registry"]
    process: ProcessInfo                       # 이벤트를 일으킨 프로세스 (모든 이벤트에 존재)
    network: NetworkInfo | None = None
    file: FileInfo | None = None
    registry: RegistryInfo | None = None
    script_text: str | None = None


class Alert(BaseModel):
    alert_id: str
    ts: datetime
    host: str
    source: Literal["rule", "anomaly"]
    rule_id: str
    title: str
    severity: Literal["low", "medium", "high", "critical"]
    techniques: list[str] = Field(default_factory=list)   # 탐지기가 추정한 ATT&CK 기법 (에이전트가 검증·보완)
    event_ids: list[str] = Field(default_factory=list)    # 근거 이벤트
    pid: int | None = None
    score: float | None = None


# 알림 상태: new → in_progress → (pending_approval →) completed / failed
# 카프카 대신 OpenSearch의 status 칸이 '대기열' 역할을 합니다.
ALERT_STATUSES = ("new", "in_progress", "pending_approval", "completed", "failed")
