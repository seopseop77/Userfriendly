"""hello_world — Phase-0 no-op plugin for verifying the plugin loading pipeline."""

from llm_tracker_sdk import BasePlugin


class HelloWorldPlugin(BasePlugin):
    name = "hello_world"
