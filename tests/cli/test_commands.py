from harness_cli.commands import expand_mentions, load_custom_commands, parse_input


def test_parse_input():
    assert parse_input("  ") == ("empty", "", "")
    assert parse_input("/mode plan") == ("slash", "mode", "plan")
    assert parse_input("/HELP") == ("slash", "help", "")
    assert parse_input("!ls -la") == ("shell", "", "ls -la")
    assert parse_input("fix the bug") == ("prompt", "", "fix the bug")
    assert parse_input("//not a command")[0] == "prompt"


def test_mentions_attach_files(workspace):
    (workspace / "README.md").write_text("# Demo")
    text, attached = expand_mentions("summarize @README.md, and ping @someone", workspace)
    assert attached == ["README.md"]
    assert text.startswith("summarize @README.md, and ping @someone")
    assert '<file path="README.md">\n# Demo\n</file>' in text


def test_mentions_never_leave_workspace(workspace):
    (workspace.parent / "secret.txt").write_text("s")
    text, attached = expand_mentions("read @../secret.txt", workspace)
    assert attached == [] and text == "read @../secret.txt"


def test_custom_commands(workspace, harness_home):
    (harness_home / "commands").mkdir(parents=True)
    (harness_home / "commands" / "review.md").write_text("description: Review code\nReview $ARGUMENTS carefully.")
    (workspace / ".harness" / "commands").mkdir(parents=True)
    (workspace / ".harness" / "commands" / "Test.md").write_text("Run the tests.")
    cmds = load_custom_commands(workspace)
    assert cmds["review"].description == "Review code"
    assert cmds["review"].render("main.py") == "Review main.py carefully."
    assert cmds["test"].render("") == "Run the tests."
    assert cmds["test"].render("only parser") == "Run the tests.\n\nonly parser"


def test_project_command_overrides_user(workspace, harness_home):
    for folder, body in ((harness_home / "commands", "user"), (workspace / ".harness" / "commands", "project")):
        folder.mkdir(parents=True)
        (folder / "x.md").write_text(body)
    assert load_custom_commands(workspace)["x"].body == "project"
