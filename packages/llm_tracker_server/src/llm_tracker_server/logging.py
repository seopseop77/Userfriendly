"""structlog configuration for the server process.

CP7 wires the Anthropic-credential scrubber into the chain
(`scrub_credential_processor`, ADR-0020 Axis 2). The scrubber sits
just before the renderer so it sees the fully-merged event dict
regardless of which call site emitted it.
"""

import logging as stdlib_logging

import structlog

from llm_tracker_server.proxy.credential import scrub_credential_processor


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(stdlib_logging, level.upper(), stdlib_logging.INFO)
    stdlib_logging.basicConfig(level=numeric_level, format="%(message)s", force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            scrub_credential_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
