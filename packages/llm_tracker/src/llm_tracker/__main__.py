"""Allow `python -m llm_tracker ...` to invoke the Typer CLI.

Used by the `claude-manage` wrapper to spawn the proxy daemon via the
same Python interpreter, regardless of whether the `llm-tracker` console
script is on PATH.
"""

from llm_tracker.cli import app

if __name__ == "__main__":
    app()
