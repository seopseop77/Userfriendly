"""hello_world — Phase-0 no-op plugin for verifying the plugin loading pipeline."""

from llm_tracker.plugin_host.base import BasePlugin


class HelloWorldPlugin(BasePlugin):
    name = "hello_world"
