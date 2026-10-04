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
    """A model factory for App/main: the first call returns `model`; a later switch returns a
    new ScriptedModel named after the requested model id, sharing the same responses."""
    built = []

    def make(spec):
        if built:
            switched = ScriptedModel(model._responses)
            switched.name = spec.model
            switched.calls = model.calls
            built.append(spec)
            return switched
        built.append(spec)
        model.name = spec.model  # like a real model: named after the id it calls
        return model

    make.built = built
    return make


def make_app(workspace, responses, lines=(), interactive=True, **settings):
    model = ScriptedModel(responses)
    out = io.StringIO()
    feeder = Feeder(lines)
    renderer = Renderer(out, color=False, input_fn=feeder)
    app = App(workspace, Settings(sandbox="off", **settings), renderer, factory(model), interactive=interactive)
    return app, model, out, feeder
