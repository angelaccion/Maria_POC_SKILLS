"""Maria bootstrap endpoint for the Claude for Office add-ins (Word/Excel/PowerPoint).

Implements the add-in's bootstrap contract (anthropics/financial-services,
claude-for-msft-365-install/commands/bootstrap.md): the add-in does a browser-side
GET on `bootstrap_url` at startup and applies the returned flat JSON on top of the
manifest parameters.

No authentication: the endpoint only serves skills and model settings. Everyone
gets the group named by `default_group` in policy.json. The optional `user`
query parameter selects another group (testing / per-user override via the
manifest URL).

Response keys used here:
  skills[]            {name, description, content(base64 SKILL.md or zip)}
  available_models[]  model-picker override
  mcp_servers[]       {url, label, headers?}  (entries without a url are dropped)
  disabled_features[] e.g. "skills.authoring"
  bootstrap_expires_at

Policy (policy.json) maps group -> {skill marketplaces, models, ...}.
Skill content is read from the GitHub marketplaces named in the group policy
(Maria_POC_SKILLS layout: .claude-plugin/marketplace.json ->
plugins/<p>/skills/<s>/SKILL.md) and inlined, so the browser never needs to
reach GitHub (no CORS exposure on skill bytes).
"""
import base64
import io
import json
import logging
import re
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

log = logging.getLogger("maria.bootstrap")
logging.basicConfig(level=logging.INFO)

ADDIN_ORIGIN = "https://pivot.claude.ai"
POLICY_PATH = Path(__file__).parent / "policy.json"
GITHUB_TOKEN = ""  # set only if the skills repo becomes private
SKILL_CACHE_TTL = 300  # seconds to cache skills fetched from GitHub
CONFIG_TTL = 900  # seconds until the add-in re-fetches this config

app = FastAPI(title="Maria Bootstrap Endpoint (Office)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ADDIN_ORIGIN],
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],  # X-Claude-User-Agent, ...
)


@app.get("/health")
@app.get("/healthz")
def health():
    """Liveness: the process is up."""
    return {"status": "ok", "service": "maria-bootstrap"}


@app.get("/ready")
def ready():
    """Readiness: policy.json parses and every group it names exists."""
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        groups = policy["groups"]
        assert policy["default_group"] in groups
        assert all(g in groups for g in policy.get("users", {}).values())
    except Exception as e:
        log.exception("readiness check failed")
        return JSONResponse({"status": "not_ready", "error": str(e)}, status_code=503)
    return {"status": "ready", "groups": sorted(groups), "default_group": policy["default_group"]}


# ---- GitHub skill loading -------------------------------------------------

_cache: dict[tuple[str, str], tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "maria-bootstrap"})
    if GITHUB_TOKEN:
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    out: dict = {}
    if m:
        for line in m.group(1).splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip()] = v.strip().strip("\"'")
    return out


def _load_marketplace(repo: str, ref: str) -> list[dict]:
    """Return [{name, description, content}] for every skill in the marketplace."""
    archive = zipfile.ZipFile(io.BytesIO(_http_get(f"https://codeload.github.com/{repo}/zip/{ref}")))
    files = {n.split("/", 1)[1]: n for n in archive.namelist() if "/" in n and not n.endswith("/")}
    market = json.loads(archive.read(files[".claude-plugin/marketplace.json"]))

    skills = []
    for plugin in market.get("plugins", []):
        source = plugin.get("source")
        if not isinstance(source, str) or not source.startswith("./"):
            log.warning("plugin %s: unsupported source %r, skipped", plugin.get("name"), source)
            continue
        base = source[2:].rstrip("/") + "/skills/"
        skill_dirs = {p[len(base):].split("/", 1)[0] for p in files if p.startswith(base) and "/" in p[len(base):]}
        for sdir in sorted(skill_dirs):
            prefix = f"{base}{sdir}/"
            members = {p[len(prefix):]: n for p, n in files.items() if p.startswith(prefix)}
            if "SKILL.md" not in members:
                continue
            raw = archive.read(members["SKILL.md"])
            meta = _frontmatter(raw.decode("utf-8", "replace"))
            name = meta.get("name", sdir)
            if len(members) == 1:
                payload = raw  # lone SKILL.md: send as text
            else:  # bundle with assets: zip with the skill folder at the root
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for rel, member in members.items():
                        z.writestr(f"{name}/{rel}", archive.read(member))
                payload = buf.getvalue()
            skills.append({
                "name": name,
                "description": meta.get("description", plugin.get("description", "")),
                "content": base64.b64encode(payload).decode("ascii"),
            })
    return skills


def _marketplace_skills(repo: str, ref: str) -> list[dict]:
    key = (repo, ref)
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < SKILL_CACHE_TTL:
            return hit[1]
    try:
        skills = _load_marketplace(repo, ref)
    except Exception:
        log.exception("failed loading marketplace %s@%s", repo, ref)
        return hit[1] if hit else []  # serve stale rather than drop the user's skills
    with _lock:
        _cache[key] = (now, skills)
    return skills



# ---- endpoint -------------------------------------------------------------


@app.get("/bootstrap")
def bootstrap(
    user: str | None = None,
    x_claude_user_agent: str | None = Header(None),
):
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    users = {k.lower(): v for k, v in policy.get("users", {}).items()}
    group = users.get((user or "").strip().lower()) or policy["default_group"]
    gp = policy["groups"][group]

    skills: dict[str, dict] = {}
    for m in gp.get("skill_marketplaces", []):
        for s in _marketplace_skills(m["repo"], m.get("ref", "main")):
            skills[s["name"]] = s

    body: dict = {
        "skills": list(skills.values()),
        "available_models": gp.get("available_models", []),
        "disabled_features": gp.get("disabled_features", []),
        "bootstrap_expires_at": int(time.time()) + CONFIG_TTL,
    }
    servers = [s for s in gp.get("mcp_servers", []) if isinstance(s, dict) and s.get("url")]
    if servers:
        body["mcp_servers"] = servers

    log.info("bootstrap group=%s app=%s skills=%s", group, x_claude_user_agent,
             [s["name"] for s in body["skills"]])
    return body
