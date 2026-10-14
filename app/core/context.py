"""Correlation ID propagation via contextvars."""

from __future__ import annotations

import contextvars
import uuid

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-"
)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def set_correlation_id(correlation_id: str) -> None:
    correlation_id_var.set(correlation_id)


def get_correlation_id() -> str:
    return correlation_id_var.get()
