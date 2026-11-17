"""가짜 LLM: API 키 없이 그래프가 끝까지 흐르는지 확인할 때 씁니다 (FAKE_LLM=true).

진짜 LLM처럼 생각하지는 않고, 정해진 규칙으로 흉내만 냅니다.
- 조사: 첫 번째에는 프로세스 족보와 활동 도구를 부르고, 두 번째에는 '조사 완료'
- 판정: 도구 결과에 업무 도구(ccmexec.exe, backupagent.exe)가 보이면 정상, 심각도가 높으면 악성, 아니면 의심
- fabricate=True: 판정 근거에 조회하지 않은 event_id를 끼워 넣습니다 (가드레일 테스트용 '거짓말쟁이')
"""
from __future__ import annotations

import json
import re
import uuid

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

BENIGN_TOOLS = ("ccmexec.exe", "backupagent.exe")
FAKE_ID = "evt-fabricated-0001"


def _usage(text: str) -> dict:
    n = max(len(text) // 4, 1)
    return {"input_tokens": n, "output_tokens": 60, "total_tokens": n + 60}


def _json_block(text: str) -> dict | list | None:
    m = re.search(r"```json\n(.*?)\n```", text, re.S)
    return json.loads(m.group(1)) if m else None


def _alert(messages) -> dict:
    for m in messages:
        if isinstance(m, HumanMessage):
            data = _json_block(m.content)
            if isinstance(data, dict) and "alert_id" in data:
                return data
    return {}


def _ids(obj) -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "event_id" and isinstance(v, str):
                out.append(v)
            else:
                out += _ids(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _ids(v)
    return out


def _tool_results(messages) -> list:
    res = []
    for m in messages:
        if isinstance(m, ToolMessage):
            try:
                res.append(json.loads(m.content))
            except (TypeError, ValueError):
                pass
    return res


class _ToolCaller:
    def __init__(self, names: list[str]):
        self.names = names

    def invoke(self, messages, config=None):
        text = "\n".join(str(m.content) for m in messages)
        called = {tc["name"] for m in messages if isinstance(m, AIMessage) for tc in (m.tool_calls or [])}
        alert = _alert(messages)
        plan = [n for n in ("get_process_tree", "get_process_activity") if n in self.names and n not in called]
        if plan and alert:
            calls = [{"name": n, "args": {"host": alert["host"], "pid": alert.get("pid") or 0},
                      "id": f"call_{uuid.uuid4().hex[:8]}", "type": "tool_call"} for n in plan]
            return AIMessage(content="", tool_calls=calls, usage_metadata=_usage(text))
        return AIMessage(content="조사 완료", usage_metadata=_usage(text))


class _Structured:
    def __init__(self, schema, include_raw: bool, fabricate: bool):
        self.schema, self.include_raw, self.fabricate = schema, include_raw, fabricate

    def invoke(self, messages, config=None):
        text = "\n".join(str(m.content) for m in messages)
        name = self.schema.__name__
        out = self._verdict(messages, text) if name == "Verdict" else self._recommend(text)
        parsed = self.schema.model_validate(out)
        if self.include_raw:
            return {"raw": AIMessage(content=json.dumps(out, ensure_ascii=False), usage_metadata=_usage(text)),
                    "parsed": parsed, "parsing_error": None}
        return parsed

    def _verdict(self, messages, text) -> dict:
        alert, results = _alert(messages), _tool_results(messages)
        seen = list(dict.fromkeys(_ids(results)))
        blob = json.dumps(results, ensure_ascii=False).lower()
        if any(t in blob for t in BENIGN_TOOLS):
            v, conf = "benign", 0.8
        elif alert.get("severity") in ("critical", "high") and len(seen) >= 2:
            v, conf = "malicious", 0.85
        else:
            v, conf = "suspicious", 0.5
        evidence = seen[:2] if seen else list(alert.get("event_ids", []))[:1]
        if self.fabricate:
            evidence = evidence[:1] + [FAKE_ID]
        return {"verdict": v, "confidence": conf, "techniques": alert.get("techniques", []) if v != "benign" else [],
                "evidence_event_ids": evidence,
                "reasoning": f"[가짜 LLM] 도구로 조회한 기록 {len(seen)}건을 보고 '{v}'로 판정했습니다."}

    def _recommend(self, text) -> dict:
        ctx = _json_block(text) or {}
        verdict = ctx.get("verdict", {}).get("verdict", "suspicious")
        sources = [h.get("source") for h in ctx.get("playbook", []) if h.get("source")]
        src = sources[0] if sources else None
        if verdict == "malicious":
            acts = [{"action": "isolate_host", "reason": "확산 차단", "approver": "SOC 팀장", "source": src},
                    {"action": "collect_forensics", "reason": "증거 보존", "source": src}]
            if any(t.startswith("T1003") for t in ctx.get("verdict", {}).get("techniques", [])):
                acts.insert(1, {"action": "reset_password", "reason": "자격증명 노출",
                                "approver": "SOC 팀장 + 계정 소유 부서장", "source": src})
        elif verdict == "benign":
            acts = [{"action": "close_as_benign", "reason": "등록된 업무 도구의 정상 활동", "source": src}]
        else:
            acts = [{"action": "monitor", "reason": "근거가 부족해 추가 관찰", "source": src}]
        return {"actions": acts, "summary": f"[가짜 LLM] '{verdict}' 판정에 따른 권고입니다."}


class FakeLLM:
    def __init__(self, fabricate: bool = False):
        self.fabricate = fabricate

    def bind_tools(self, tools, **_):
        return _ToolCaller([getattr(t, "name", getattr(t, "__name__", "")) for t in tools])

    def with_structured_output(self, schema, include_raw: bool = False, **_):
        return _Structured(schema, include_raw, self.fabricate)
