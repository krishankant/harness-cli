import os
from pathlib import Path


def test_imports_the_selected_implementation():
    import harnessy

    in_solutions = "solutions" in Path(harnessy.__file__).parts
    assert in_solutions == (os.environ.get("HARNESSY_IMPL") == "solutions")
