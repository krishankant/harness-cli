"""The capstone agents (week 8). Each is configuration only: a system prompt, tools, hooks and
limits on the same Agent. If you had to change the harness to build one, that's the lesson."""

from harnessy.agents import code, data, research

AGENTS = {"research": research.make_agent, "code": code.make_agent, "data": data.make_agent}
