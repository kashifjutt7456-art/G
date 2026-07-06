"""Buyer Network Runner — structured logging (stdout only; GitHub Actions
captures stdout as the artifact log, same as the scraper fleet's convention)."""

from __future__ import annotations

import logging
import sys


def get_logger(name: str = "buyer_network_runner") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger
