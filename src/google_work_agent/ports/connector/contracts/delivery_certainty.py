"""Connector-neutral certainty for an attempted external delivery."""

from enum import StrEnum


class DeliveryCertainty(StrEnum):
    NOT_SENT = "NOT_SENT"
    MAY_HAVE_BEEN_SENT = "MAY_HAVE_BEEN_SENT"
    SENT_RESPONSE_LOST = "SENT_RESPONSE_LOST"


__all__ = ["DeliveryCertainty"]
