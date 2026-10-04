"""The App: one conversation in one workspace. It owns the settings, the model, the tools, the
engine and the session, and runs turns for both the REPL and headless mode."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from harness_cli.config import Settings
from harness_cli.engine import ApprovalRequest, Done, Engine, Interrupted, TextDelta, ToolEnd, ToolStart
from harness_cli.instructions import build_system_prompt
from harness_cli.permissions import PermissionHook
from harness_cli.render import Renderer
from harness_cli.session import Session
from harness_cli.tools import SessionTodo, build_tools, start_mcp
from harnessy.loop import RunResult
from harnessy.models.base import Model
from harness_cli.models import ModelSpec, Registry, build_model
from harnessy.types import Message

ModelFactory = Callable[[ModelSpec], Model]


class App:
    def __init__(
        self,
        workspace: Path,
        settings: Settings,
        renderer: Renderer,
        model_factory: ModelFactory = build_model,
        interactive: bool = True,
        session: Session | None = None,
        registry: Registry | None = None,
    ):
        self.workspace = Path(workspace).resolve()
        self.settings = settings
        self.model_factory = model_factory
        self.renderer = renderer
        self.interactive = interactive
        self.registry = registry or Registry.from_settings(settings)
        self.spec = self.registry.resolve(settings.model)
        self.model = model_factory(self.spec)
        self.todo = SessionTodo()
        self.permissions = PermissionHook(settings.permission_mode, [], settings.allow, settings.deny)
        self.mcp_tools, self.mcp_clients, self.mcp_errors = start_mcp(settings.mcp_servers, self.workspace)
        self.session = session or Session.new(self.workspace, self.spec.provider, self.spec.model)
        self.session.provider, self.session.model = self.spec.provider, self.spec.model  # a resumed one may switch
        self.engine: Engine
        self.build()
        if settings.max_cost_usd is not None and not self.engine.priced():
            renderer.warn(f"No price for model '{self.model.name}' in harnessy/cost.py: --max-cost can't be enforced.")

    def build(self) -> None:
        """(Re)build tools, system prompt and engine for the current model; keeps the session,
        the todo list, and the permission hook with its "always" answers."""
        tools = [*build_tools(self.workspace, self.settings, self.todo, self.model, hooks=[self.permissions]), *self.mcp_tools]
        self.permissions.add_tools(t.name for t in tools)
        self.system = build_system_prompt(self.workspace, self.settings, [t.name for t in tools])
        old = getattr(self, "engine", None)
        self.engine = Engine(
            self.model,
            tools,
            self.system,
            interactive=self.interactive,
            hooks=[self.todo],
            max_steps=self.settings.max_steps,
            max_cost_usd=self.settings.max_cost_usd,
            context_budget_tokens=self.settings.context_budget_tokens,
            permissions=self.permissions,
            prices=self.registry.prices(),
        )
        if old is not None:
            self.engine.usage, self.engine.cost_usd = old.usage, old.cost_usd
        else:
            self.engine.usage, self.engine.cost_usd = self.session.usage, self.session.cost_usd

    @property
    def tools(self):
        return self.engine.tools

    def set_model(self, name: str) -> None:
        """Switch to another model, of any provider; the conversation carries over. On an error
        (unknown name, missing key) nothing changes."""
        spec = self.registry.resolve(name)
        model = self.model_factory(spec)
        self.spec, self.model = spec, model
        self.session.provider, self.session.model = spec.provider, spec.model
        self.build()

    def new_session(self) -> None:
        self.session = Session.new(self.workspace, self.spec.provider, self.spec.model)
        self.todo.reset()
        self.engine.reset_context()
        self.engine.usage, self.engine.cost_usd = self.session.usage, self.session.cost_usd

    def switch_session(self, session: Session) -> None:
        self.session = session
        self.todo.reset()
        self.engine.reset_context()
        self.engine.usage, self.engine.cost_usd = session.usage, session.cost_usd

    # --- running a turn ---

    def run_turn(self, prompt: str, on_event: Callable[[Any], None] | None = None) -> RunResult:
        """Run one turn, show it (or hand events to on_event), save the session, return the result."""
        handle = on_event or self.show
        gen = self.engine.turn(prompt, self.session.messages)
        result: RunResult | None = None
        while result is None:
            try:
                for event in gen:
                    if isinstance(event, ApprovalRequest):
                        self._answer(event)
                    elif isinstance(event, Interrupted):
                        self._interrupted()
                    else:
                        handle(event)
                    if isinstance(event, Done):
                        result = event.result
            except KeyboardInterrupt:
                if self.engine._cancel.flag.is_set():
                    raise  # a second Ctrl-C in the same turn: give up on it
                self.engine.cancel()
                self._interrupted()
        self._record(result)
        return result

    def _interrupted(self) -> None:
        self.renderer.warn("⏹ interrupting… (a running tool finishes first; Ctrl-C again to quit)")

    def _answer(self, request: ApprovalRequest) -> None:
        if not self.interactive:
            request.reply.put("n")
            return
        try:
            answer = self.renderer.ask(request.call)
        except KeyboardInterrupt:
            self.engine.cancel()
            answer = "n"
        request.reply.put(answer)

    def show(self, event: Any) -> None:
        r = self.renderer
        if isinstance(event, TextDelta):
            r.text(event.text)
        elif isinstance(event, ToolStart):
            r.tool_start(event.call)
        elif isinstance(event, ToolEnd):
            r.tool_end(event.call, event.result)
        elif isinstance(event, Done):
            r.end_text()
            res = event.result
            if res.stop_reason != "end_turn":
                detail = f": {res.error}" if res.error else ""
                r.warn(f"[stopped: {res.stop_reason}{detail}]")

    def _record(self, result: RunResult) -> None:
        messages = list(result.messages)
        # A turn that ended early can leave the history ending on a user message; close it so
        # the next prompt keeps roles alternating for every provider.
        if messages and messages[-1].role == "user":
            messages.append(Message("assistant", text=f"(turn ended early: {result.stop_reason})"))
        self.session.messages = messages
        self.session.usage, self.session.cost_usd = self.engine.usage, self.engine.cost_usd
        self.session.save()

    def close(self) -> None:
        for client in self.mcp_clients:
            try:
                client.close()
            except Exception:
                pass
