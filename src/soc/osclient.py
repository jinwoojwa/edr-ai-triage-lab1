"""OpenSearch 연결.

BACKEND=real   → 진짜 OpenSearch (opensearch-py)
BACKEND=memory → 메모리 안의 작은 흉내(MemoryOpenSearch). 인프라 없이 API·테스트를 돌릴 때 씁니다.

두 클라이언트는 이 실습에서 쓰는 메서드 이름과 결과 모양이 같습니다.
그래서 조사 도구는 어느 쪽인지 몰라도 같은 검색 문(DSL)으로 동작합니다.
※ 흉내는 매핑을 보지 않습니다. text 칸에 term 검색을 해도 찾아 줍니다.
  keyword와 text의 차이는 진짜 OpenSearch에서만 드러납니다 (1일차 3-🔍-2).
"""
from __future__ import annotations

import copy
import fnmatch
import itertools
from datetime import datetime
from functools import lru_cache

from .config import settings


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


# ---------------------------------------------------------------------------- 메모리 흉내
def _get(doc: dict, path: str):
    if path.endswith(".keyword"):
        path = path[: -len(".keyword")]
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _cmp_value(v):
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return v
    return v


def _match(doc: dict, q: dict) -> bool:
    if not q or "match_all" in q:
        return True
    (kind, body), = q.items()
    if kind == "bool":
        def as_list(x):
            return x if isinstance(x, list) else [x]
        ok = all(_match(doc, c) for c in as_list(body.get("filter", [])) + as_list(body.get("must", [])))
        ok = ok and not any(_match(doc, c) for c in as_list(body.get("must_not", [])))
        should = as_list(body.get("should", []))
        if should and ok:
            need = body.get("minimum_should_match", 1 if not (body.get("filter") or body.get("must")) else 0)
            ok = sum(_match(doc, c) for c in should) >= int(need)
        return ok
    (field, cond), = body.items()
    val = _get(doc, field)
    if kind == "term":
        cond = cond["value"] if isinstance(cond, dict) else cond
        return val == cond
    if kind == "terms":
        return val in cond
    if kind == "exists":
        return _get(doc, body["field"]) is not None
    if kind == "prefix":
        return isinstance(val, str) and val.startswith(cond if isinstance(cond, str) else cond["value"])
    if kind in ("match", "match_phrase"):
        text = cond["query"] if isinstance(cond, dict) else cond
        return isinstance(val, str) and all(t.lower() in val.lower() for t in str(text).split())
    if kind == "range":
        if val is None:
            return False
        v = _cmp_value(val)
        for op, x in cond.items():
            if op == "format":
                continue
            x = _cmp_value(x)
            if (op == "gte" and not v >= x) or (op == "gt" and not v > x) or \
               (op == "lte" and not v <= x) or (op == "lt" and not v < x):
                return False
        return True
    raise NotImplementedError(f"메모리 흉내가 지원하지 않는 검색: {kind}")


class _Indices:
    def __init__(self, store: "MemoryOpenSearch"):
        self.s = store

    def exists(self, index):
        return any(self.s._names(index))

    def create(self, index, body=None, **_):
        self.s.docs.setdefault(index, {})
        return {"acknowledged": True}

    def delete(self, index, **_):
        for n in list(self.s._names(index)):
            self.s.docs.pop(n, None)
        return {"acknowledged": True}

    def put_index_template(self, name, body, **_):
        self.s.templates[name] = body
        return {"acknowledged": True}

    def refresh(self, index=None, **_):
        return {}


class _Cluster:
    def health(self, **_):
        return {"status": "green", "number_of_nodes": 1}


class MemoryOpenSearch:
    def __init__(self):
        self.docs: dict[str, dict[str, dict]] = {}
        self.meta: dict[tuple[str, str], int] = {}
        self.templates: dict = {}
        self._seq = itertools.count(1)
        self.indices = _Indices(self)
        self.cluster = _Cluster()

    def _names(self, index: str):
        pats = index.split(",")
        return [n for n in self.docs if any(fnmatch.fnmatch(n, p) for p in pats)]

    def ping(self):
        return True

    def index(self, index, body, id=None, refresh=None, **_):
        id = id or f"auto-{next(self._seq)}"
        self.docs.setdefault(index, {})[id] = copy.deepcopy(body)
        self.meta[(index, id)] = next(self._seq)
        return {"_id": id, "result": "created"}

    def get(self, index, id, **_):
        for n in self._names(index):
            if id in self.docs[n]:
                return {"_index": n, "_id": id, "_source": copy.deepcopy(self.docs[n][id]),
                        "_seq_no": self.meta[(n, id)], "_primary_term": 1, "found": True}
        raise NotFound(f"{index}/{id}")

    def update(self, index, id, body, if_seq_no=None, if_primary_term=None, refresh=None, **_):
        cur = self.get(index, id)
        if if_seq_no is not None and cur["_seq_no"] != if_seq_no:
            raise Conflict(f"{index}/{id} seq_no {cur['_seq_no']} != {if_seq_no}")
        n = cur["_index"]
        self.docs[n][id].update(copy.deepcopy(body.get("doc", {})))
        self.meta[(n, id)] = next(self._seq)
        return {"_id": id, "result": "updated"}

    def _hits(self, index, body):
        body = body or {}
        q = body.get("query", {"match_all": {}})
        rows = [(n, i, d) for n in self._names(index) for i, d in self.docs[n].items() if _match(d, q)]
        for spec in reversed(body.get("sort", [])):
            (field, order), = (spec.items() if isinstance(spec, dict) else [(spec, "asc")])
            order = order["order"] if isinstance(order, dict) else order
            rows.sort(key=lambda r: (_cmp_value(_get(r[2], field)) is None, _cmp_value(_get(r[2], field)) or 0),
                      reverse=(order == "desc"))
        return rows

    def search(self, index, body=None, size=None, **_):
        rows = self._hits(index, body)
        n = size or (body or {}).get("size", 10)
        hits = [{"_index": ix, "_id": i, "_score": 1.0, "_source": copy.deepcopy(d),
                 "_seq_no": self.meta[(ix, i)], "_primary_term": 1} for ix, i, d in rows[:n]]
        return {"hits": {"total": {"value": len(rows)}, "hits": hits}}

    def count(self, index, body=None, **_):
        return {"count": len(self._hits(index, body))}


# ---------------------------------------------------------------------------- 공통 입구
@lru_cache(maxsize=1)
def get_client():
    if settings.backend == "memory":
        return MemoryOpenSearch()
    from opensearchpy import OpenSearch

    return OpenSearch(hosts=[settings.opensearch_url], timeout=30, http_compress=True)


def bulk_index(client, index: str, docs: list[dict], id_field: str | None = None, refresh: bool = True) -> int:
    """여러 문서를 한 번에 넣습니다. 진짜 OpenSearch는 _bulk API, 흉내는 하나씩."""
    if isinstance(client, MemoryOpenSearch):
        for d in docs:
            client.index(index=index, id=d.get(id_field) if id_field else None, body=d)
        return len(docs)
    from opensearchpy import helpers

    actions = ({"_index": index, "_id": d[id_field] if id_field else None, "_source": d} for d in docs)
    ok, _ = helpers.bulk(client, actions, refresh=refresh, chunk_size=500)
    return ok


def is_not_found(exc: Exception) -> bool:
    if isinstance(exc, NotFound):
        return True
    from opensearchpy.exceptions import NotFoundError

    return isinstance(exc, NotFoundError)


def is_conflict(exc: Exception) -> bool:
    if isinstance(exc, Conflict):
        return True
    from opensearchpy.exceptions import ConflictError

    return isinstance(exc, ConflictError)
