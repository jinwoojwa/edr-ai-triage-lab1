"""룰 기반 탐지 (Sigma 룰을 파이썬으로 단순화).

룰 = (이벤트 하나 또는 최근 이벤트 묶음) → 알림.  모든 룰은 ATT&CK 기법 ID를 붙입니다.
- 무상태(stateless) 룰: 이벤트 한 건만 보고 판단
- 상태(stateful) 룰: 호스트별 '시간 창(window)' 안의 이벤트를 세어 판단 (랜섬웨어, 비컨)

룰 중 R007, R009는 일부러 단순하게 만들어 오탐을 냅니다. 에이전트가 오탐을 걸러내는지 보기 위해서입니다.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from datetime import timedelta

from ..schema import Alert, Event

OFFICE = {"winword.exe", "excel.exe", "powerpnt.exe", "outlook.exe"}
SHELLS = {"cmd.exe", "powershell.exe", "pwsh.exe", "wscript.exe", "cscript.exe", "mshta.exe"}
ENC_FLAG = re.compile(r"\s-(e|en|enc|enco|encodedcommand)\s", re.I)


def _alert(rule_id, title, sev, techniques, e: Event, extra_ids=()) -> Alert:
    ids = [e.event_id, *extra_ids]
    aid = "al-" + hashlib.sha1(f"{rule_id}:{e.host}:{ids[0]}".encode()).hexdigest()[:12]   # 같은 근거 → 같은 id (멱등)
    return Alert(alert_id=aid, ts=e.ts, host=e.host, source="rule", rule_id=rule_id, title=title,
                 severity=sev, techniques=techniques, event_ids=ids, pid=e.process.pid)


# ---------------------------------------------------------------- 무상태 룰
def r_encoded_powershell(e: Event):
    p = e.process
    if e.type == "process" and p.name.lower() in {"powershell.exe", "pwsh.exe"} and ENC_FLAG.search(f" {p.cmdline} "):
        return _alert("R001", "인코딩된 PowerShell 명령 실행", "high", ["T1059.001"], e)


def r_office_spawns_shell(e: Event):
    p = e.process
    if e.type == "process" and (p.parent_name or "").lower() in OFFICE and p.name.lower() in SHELLS:
        return _alert("R002", f"오피스 프로그램({p.parent_name})이 셸({p.name}) 실행", "high", ["T1566.001", "T1204.002"], e)


def r_lsass_dump(e: Event):
    c = e.process.cmdline.lower()
    if e.type == "process" and "comsvcs.dll" in c and "minidump" in c:
        return _alert("R003", "comsvcs.dll MiniDump를 이용한 LSASS 메모리 덤프 의심", "critical", ["T1003.001"], e)


def r_ps_bypass(e: Event):
    """일부러 단순하게 만든 룰: ExecutionPolicy Bypass만 보고 울립니다.
    IT 자산관리 도구(ccmexec.exe)도 이렇게 실행하므로 오탐이 납니다 → 에이전트가 걸러야 할 몫."""
    p = e.process
    if e.type == "process" and p.name.lower() in {"powershell.exe", "pwsh.exe"} and "bypass" in p.cmdline.lower() \
            and not ENC_FLAG.search(f" {p.cmdline} "):
        return _alert("R009", "PowerShell 실행 정책 우회(Bypass)", "medium", ["T1059.001"], e)


def r_run_key(e: Event):
    if e.type == "registry" and e.registry and "\\currentversion\\run" in e.registry.key.lower():
        sev = "high" if not e.registry.value.lower().startswith("c:\\program files") else "low"
        return _alert("R004", "Run 레지스트리 키에 자동 실행 등록", sev, ["T1547.001"], e)


def r_psexec(e: Event):
    n = e.process.name.lower()
    if e.type == "process" and (n == "psexesvc.exe" or (n == "psexec.exe" and "\\\\" in e.process.cmdline)):
        return _alert("R005", "PsExec 원격 실행", "high", ["T1021.002", "T1569.002"], e)


def r_shadow_delete(e: Event):
    c = e.process.cmdline.lower()
    if e.type == "process" and "vssadmin" in c and "delete shadows" in c:
        return _alert("R006", "볼륨 섀도 복사본 삭제", "critical", ["T1490"], e)


STATELESS = [r_encoded_powershell, r_office_spawns_shell, r_lsass_dump, r_ps_bypass, r_run_key, r_psexec, r_shadow_delete]


# ---------------------------------------------------------------- 상태 룰
class RansomwareRenameRule:
    """같은 프로세스가 짧은 시간에 파일을 대량으로 이름 변경.
    일부러 확장자를 보지 않습니다 → 백업 프로그램의 정상 교체(.bak → .bak.old)도 울립니다 (오탐 → 에이전트 몫)."""

    window = timedelta(seconds=30)
    threshold = 20

    def __init__(self):
        self.buf: dict[tuple[str, int], deque] = defaultdict(deque)
        self.fired: set[tuple[str, int]] = set()

    def __call__(self, e: Event):
        if e.type != "file" or not e.file or e.file.action != "rename":
            return None
        k = (e.host, e.process.pid)
        q = self.buf[k]
        q.append(e)
        while q and e.ts - q[0].ts > self.window:
            q.popleft()
        if len(q) >= self.threshold and k not in self.fired:
            self.fired.add(k)
            return _alert("R007", f"{e.process.name}가 {len(q)}개 파일을 단시간에 이름 변경 (암호화 의심)",
                          "critical", ["T1486"], e, extra_ids=[x.event_id for x in list(q)[:5]])
        return None


class BeaconRule:
    """같은 프로세스가 같은 외부 IP로 일정 간격 연결을 반복 (C2 비컨)."""

    min_count = 5
    max_jitter = 0.2   # 간격의 변동계수(표준편차/평균)가 이보다 작으면 '규칙적'

    def __init__(self):
        self.buf: dict[tuple[str, int, str], list] = defaultdict(list)
        self.fired: set = set()

    def __call__(self, e: Event):
        if e.type != "network" or not e.network or e.network.dst_ip.startswith("10."):
            return None
        k = (e.host, e.process.pid, e.network.dst_ip)
        self.buf[k].append(e)
        evs = self.buf[k][-10:]
        if len(evs) < self.min_count or k in self.fired:
            return None
        gaps = [(b.ts - a.ts).total_seconds() for a, b in zip(evs, evs[1:])]
        mean = sum(gaps) / len(gaps)
        if mean <= 0:
            return None
        cv = (sum((g - mean) ** 2 for g in gaps) / len(gaps)) ** 0.5 / mean
        if cv < self.max_jitter:
            self.fired.add(k)
            return _alert("R008", f"{e.process.name} → {e.network.dst_ip} 주기적 연결 (C2 비컨 의심, 간격≈{mean:.0f}s)",
                          "high", ["T1071.001"], e, extra_ids=[x.event_id for x in evs[:-1]])
        return None


class RuleEngine:
    def __init__(self):
        self.stateful = [RansomwareRenameRule(), BeaconRule()]

    def process(self, e: Event) -> list[Alert]:
        out = []
        for r in STATELESS:
            a = r(e)
            if a:
                out.append(a)
        for r in self.stateful:
            a = r(e)
            if a:
                out.append(a)
        return out
