"""Week 9: connect an agent to an MCP server.

Run from the repo root:
    uv run python -m scripts.week9_demo                    # the bundled notes server
    uv run python -m scripts.week9_demo --server "npx -y @modelcontextprotocol/server-everything"
The bundled server is ours, so its tools are trusted. Any other server's tools carry all three
lethal-trifecta tags and need your approval (or --yes).
"""

from dotenv import load_dotenv

load_dotenv()

import argparse  # noqa: E402
import shlex  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

from harnessy.approvals import ApprovalHook, terminal_approver  # noqa: E402
from harnessy.loop import Agent  # noqa: E402
from harnessy.mcp import ALL_TAGS, McpClient, mcp_tools  # noqa: E402
from harnessy.models.anthropic import AnthropicModel  # noqa: E402
from harnessy.models.openai import OpenAIModel  # noqa: E402

PROVIDERS = {"anthropic": AnthropicModel, "openai": OpenAIModel}
NOTES_SERVER = Path(__file__).resolve().with_name("mcp_notes_server.py")
NOTES_TASK = (
    "Save three short notes: one about the agent loop, one about context windows, and one about MCP. "
    "Then search the notes for 'context' and tell me which notes matched."
)
OTHER_TASK = "Tell me which tools you have. Then call one harmless tool and report exactly what it returned."


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=list(PROVIDERS), default="anthropic")
    parser.add_argument("--server", help="a stdio MCP server command line (default: the bundled notes server)")
    parser.add_argument("--yes", action="store_true", help="approve every tool call automatically")
    args = parser.parse_args()
    try:
        model = PROVIDERS[args.provider]()
        with tempfile.TemporaryDirectory() as workspace:
            if args.server:
                command, prefix, trusted, task = shlex.split(args.server), "mcp", False, OTHER_TASK
            else:
                command, prefix, trusted, task = [sys.executable, str(NOTES_SERVER), str(Path(workspace) / "notes.json")], "notes", True, NOTES_TASK
            with McpClient.stdio(command) as client:
                name = client.server_info.get("name", "?")
                print(f"== connected to {name}: {client.era} era, protocol {client.protocol_version}")
                tools = mcp_tools(client, prefix=prefix, tags=() if trusted else ALL_TAGS)
                for t in tools:
                    print(f"   {t.name}: {t.spec.description[:80]}")
                hooks = []
                if not trusted:
                    approver = (lambda call: True) if args.yes else terminal_approver
                    hooks = [ApprovalHook({}, approver=approver, default="ask")]
                system = "Use the tools. Be brief." + (f"\nServer instructions: {client.instructions}" if client.instructions else "")
                result = Agent(model, tools=tools, system=system, hooks=hooks, max_steps=10, verbose=True).run(task)
                print(f"\nstop={result.stop_reason} steps={len(result.steps)} cost=${result.cost_usd:.4f}")
                print(f"answer: {result.final_text}")
    except NotImplementedError as e:
        print(f"Finish the exercises first ({e})")
        return 1
    except Exception as e:
        print(f"failed: {type(e).__name__}: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
