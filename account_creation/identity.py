"""Synthetic identity generation for CREATE_BUYER_ACCOUNT jobs. In-memory only
— never written to CSV/disk (that was VVRO's plaintext-credential problem)."""

from __future__ import annotations

import random
import string
from dataclasses import dataclass
from typing import Optional

FIRST_NAMES = ["John", "Mike", "David", "Chris", "Tom", "Alex", "Sam", "Jordan"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis"]


@dataclass
class Identity:
    first_name: str
    last_name: str
    email: str
    password: str
    # Fiverr signup asks for a separate handle even though it reuses the
    # Outlook email/password — set once Fiverr signup actually runs.
    fiverr_username: Optional[str] = None


def generate_identity() -> Identity:
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    alpha = "".join(random.choices(string.ascii_lowercase, k=9))
    nums = "".join(random.choices(string.digits, k=2))
    local_part = f"{first.lower()}{alpha}{nums}"
    password = f"{first}.{''.join(random.choices(string.ascii_lowercase, k=3))}{random.randint(100, 999)}"
    return Identity(first_name=first, last_name=last, email=f"{local_part}@outlook.com", password=password)
