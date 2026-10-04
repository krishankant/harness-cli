import io

from harness_cli.app import App
from harness_cli.config import Settings
from harness_cli.render import Renderer
from harnessy.models.scripted import ScriptedModel


class Feeder:
    """input() replacement: returns prepared lines, then raises EOFError."""

    def __init__(self, lines):
        self.lines = list(lines)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


def factory(model):
    def make(provider, name=None):
        if name and name != model.name:
            switched = ScriptedModel(model._responses)
            switched.name = name
            return switched
        return model

    return make


def make_app(workspace, responses, lines=(), interactive=True, **settings):
    model = ScriptedModel(responses)
    out = io.StringIO()
    feeder = Feeder(lines)
    renderer = Renderer(out, color=False, input_fn=feeder)
    app = App(workspace, Settings(sandbox="off", **settings), factory(model), renderer, interactive=interactive)
    return app, model, out, feeder
