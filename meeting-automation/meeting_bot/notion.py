"""최소한의 Notion REST API 클라이언트 + 블록 빌더."""
import re
import time

import httpx

from .config import CONFIG

API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TEXT_LIMIT = 1900   # rich_text 1개당 2000자 제한
BLOCK_BATCH = 100   # children 추가 1회당 100블록 제한


class Notion:
    def __init__(self, token: str | None = None):
        token = token or CONFIG.notion_token
        if not token:
            raise SystemExit("NOTION_TOKEN 이 필요합니다.")
        self.http = httpx.Client(
            base_url=API,
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        self._users: list[dict] | None = None

    def _req(self, method: str, path: str, **kw) -> dict:
        for attempt in range(5):
            resp = self.http.request(method, path, **kw)
            if resp.status_code == 429 or resp.status_code >= 500:
                time.sleep(float(resp.headers.get("Retry-After", 2 ** attempt)))
                continue
            if resp.is_error:
                raise RuntimeError(f"Notion API {resp.status_code}: {resp.text}")
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    # --- pages / databases ---------------------------------------------------
    def create_page(self, database_id: str, properties: dict, children: list | None = None) -> dict:
        children = children or []
        page = self._req("POST", "/pages", json={
            "parent": {"database_id": database_id},
            "properties": properties,
            "children": children[:BLOCK_BATCH],
        })
        if len(children) > BLOCK_BATCH:
            self.append_blocks(page["id"], children[BLOCK_BATCH:])
        return page

    def create_child_page(self, parent_page_id: str, title: str, children: list) -> dict:
        page = self._req("POST", "/pages", json={
            "parent": {"page_id": parent_page_id},
            "properties": {"title": {"title": rich(title)}},
            "children": children[:BLOCK_BATCH],
        })
        if len(children) > BLOCK_BATCH:
            self.append_blocks(page["id"], children[BLOCK_BATCH:])
        return page

    def update_page(self, page_id: str, properties: dict) -> dict:
        return self._req("PATCH", f"/pages/{page_id}", json={"properties": properties})

    def append_blocks(self, block_id: str, children: list) -> None:
        for i in range(0, len(children), BLOCK_BATCH):
            self._req("PATCH", f"/blocks/{block_id}/children",
                      json={"children": children[i:i + BLOCK_BATCH]})

    def create_database(self, parent_page_id: str, title: str, properties: dict) -> dict:
        return self._req("POST", "/databases", json={
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": rich(title),
            "properties": properties,
        })

    def query(self, database_id: str, filter_: dict | None = None, sorts: list | None = None) -> list[dict]:
        results, cursor = [], None
        while True:
            body = {"page_size": 100}
            if filter_:
                body["filter"] = filter_
            if sorts:
                body["sorts"] = sorts
            if cursor:
                body["start_cursor"] = cursor
            data = self._req("POST", f"/databases/{database_id}/query", json=body)
            results += data["results"]
            if not data.get("has_more"):
                return results
            cursor = data["next_cursor"]

    def search(self, query: str, limit: int = 10) -> list[dict]:
        data = self._req("POST", "/search", json={
            "query": query, "page_size": limit,
            "filter": {"property": "object", "value": "page"},
        })
        return data["results"]

    def children(self, block_id: str) -> list[dict]:
        results, cursor = [], None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._req("GET", f"/blocks/{block_id}/children", params=params)
            results += data["results"]
            if not data.get("has_more"):
                return results
            cursor = data["next_cursor"]

    def page_text(self, page_id: str, depth: int = 2) -> str:
        """페이지 본문을 평문으로 (토글 등 하위 블록 depth 단계까지)."""
        lines = []
        for b in self.children(page_id):
            body = b.get(b["type"], {})
            text = plain(body.get("rich_text", []))
            if text:
                lines.append(text)
            if b.get("has_children") and depth > 0 and b["type"] not in ("child_page", "child_database"):
                lines.append(self.page_text(b["id"], depth - 1))
        return "\n".join(l for l in lines if l)

    # --- users ---------------------------------------------------------------
    def users(self) -> list[dict]:
        if self._users is None:
            self._users, cursor = [], None
            while True:
                params = {"page_size": 100}
                if cursor:
                    params["start_cursor"] = cursor
                data = self._req("GET", "/users", params=params)
                self._users += [u for u in data["results"] if u.get("type") == "person"]
                if not data.get("has_more"):
                    break
                cursor = data["next_cursor"]
        return self._users

    def find_user(self, name: str | None) -> str | None:
        """이름으로 워크스페이스 멤버 찾기 (공백 무시, 부분일치)."""
        if not name:
            return None
        key = re.sub(r"\s+", "", name).lower()
        for u in self.users():
            uname = re.sub(r"\s+", "", u.get("name") or "").lower()
            if uname and (uname == key or key in uname or uname in key):
                return u["id"]
        return None


# ---------------------------------------------------------------------------
# 속성/블록 헬퍼
# ---------------------------------------------------------------------------

def rich(text: str) -> list[dict]:
    text = text or ""
    return [{"type": "text", "text": {"content": text[i:i + TEXT_LIMIT]}}
            for i in range(0, max(len(text), 1), TEXT_LIMIT)] if text else []


def plain(rich_text: list[dict]) -> str:
    return "".join(r.get("plain_text", "") for r in rich_text)


def prop_title(page: dict) -> str:
    for p in page["properties"].values():
        if p["type"] == "title":
            return plain(p["title"])
    return ""


def prop_text(page: dict, name: str) -> str:
    p = page["properties"].get(name)
    if not p:
        return ""
    if p["type"] in ("rich_text", "title"):
        return plain(p[p["type"]])
    if p["type"] == "select":
        return (p["select"] or {}).get("name", "")
    if p["type"] == "multi_select":
        return ", ".join(o["name"] for o in p["multi_select"])
    if p["type"] == "date":
        return (p["date"] or {}).get("start", "")
    if p["type"] == "people":
        return ", ".join(u.get("name", "") for u in p["people"])
    return ""


def _block(kind: str, text: str, **extra) -> dict:
    return {"object": "block", "type": kind, kind: {"rich_text": rich(text), **extra}}


def heading(text: str, level: int = 2) -> dict:
    return _block(f"heading_{level}", text)


def para(text: str) -> dict:
    return _block("paragraph", text)


def bullet(text: str) -> dict:
    return _block("bulleted_list_item", text)


def numbered(text: str) -> dict:
    return _block("numbered_list_item", text)


def todo(text: str, checked: bool = False) -> dict:
    return _block("to_do", text, checked=checked)


def callout(text: str, emoji: str = "💡") -> dict:
    return _block("callout", text, icon={"type": "emoji", "emoji": emoji})


def toggle(text: str, children: list) -> dict:
    return _block("toggle", text, children=children[:BLOCK_BATCH])


def divider() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def markdown_blocks(md: str) -> list[dict]:
    """간단한 마크다운 → Notion 블록 (제목/목록/체크박스/인용/문단)."""
    blocks = []
    for raw in md.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            continue
        s_clean = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        if s.startswith("### "):
            blocks.append(heading(s_clean[4:], 3))
        elif s.startswith("## "):
            blocks.append(heading(s_clean[3:], 2))
        elif s.startswith("# "):
            blocks.append(heading(s_clean[2:], 1))
        elif re.match(r"^[-*] \[( |x)\] ", s):
            blocks.append(todo(s_clean[6:], checked=s[3] == "x"))
        elif s.startswith(("- ", "* ")):
            blocks.append(bullet(s_clean[2:]))
        elif re.match(r"^\d+[.)] ", s):
            blocks.append(numbered(re.sub(r"^\d+[.)] ", "", s_clean)))
        elif s.startswith("> "):
            blocks.append(_block("quote", s_clean[2:]))
        elif s in ("---", "***"):
            blocks.append(divider())
        else:
            blocks.append(para(s_clean))
    return blocks


def page_url(page: dict) -> str:
    return page.get("url") or f"https://www.notion.so/{page['id'].replace('-', '')}"
