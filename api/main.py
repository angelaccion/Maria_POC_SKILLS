"""Bootstrap endpoint POC.

Mirrors the WS3 bootstrap endpoint described in the Maria v2 migration
plan (infra/migration/Maria v2 - ...md, Sections 5, 7 and 11): a client
signs in, tells the endpoint who it is, and gets back the skills + policy
it should load. In production that's an Entra JWT resolved to a Workspace
group, backed by a versioned YAML policy. Here both are stubbed: the
caller passes a user email, and the user->group->policy chain is a
static JSON file (policy.json) instead of BigQuery/Entra.

Per the real design, skills are assigned by group only - there is no
per-user skill grant (Section 11, item 6).

The response shape for skills follows Claude Desktop's actual bootstrap
contract (claude.com/docs/third-party/claude-desktop/extensions): a
bare skill name is not deliverable on its own. Entitled groups get an
`allowedPluginMarketplaces` entry with `"source": "github"`, pointing
at github.com/angelaccion/Maria_POC_SKILLS, whose `.claude-plugin/
marketplace.json` lists the quick-brief plugin by a relative path to
its real `.claude-plugin/plugin.json` + `skills/quick-brief/SKILL.md`.
Git's own commit SHA is the integrity guarantee here, so no archive or
sha256 pin is needed (contrast the HTTPS-hosted "url" source, which
does need both). mcp_servers is left as a simplified name list for
this POC.
"""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException

app = FastAPI(title="Maria Bootstrap Endpoint (POC)")

POLICY_PATH = Path(__file__).parent / "policy.json"


def _load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text())


@app.get("/bootstrap")
def bootstrap(user: str):
    policy = _load_policy()

    group = policy["users"].get(user)
    if group is None:
        raise HTTPException(
            status_code=404, detail=f"No Workspace group mapping for user '{user}'"
        )

    group_policy = policy["groups"].get(group)
    if group_policy is None:
        raise HTTPException(
            status_code=500, detail=f"User '{user}' maps to unknown group '{group}'"
        )

    return {
        "user": user,
        "group": group,
        "allowedPluginMarketplaces": group_policy["allowedPluginMarketplaces"],
        "mcp_servers": group_policy["mcp_servers"],
        "available_models": group_policy["available_models"],
        "disabled_features": group_policy["disabled_features"],
        "otlp_endpoint": group_policy["otlp_endpoint"],
    }
