"""structlog configuration for the server process.

CP7 will extend the processor chain with the Anthropic-credential
scrubber (ADR-0020). For CP1 this only wires level + JSON renderer.
"""

import logging as stdlib_logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(stdlib_logging, level.upper(), stdlib_logging.INFO)
    stdlib_logging.basicConfig(level=numeric_level, format="%(message)s", force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
