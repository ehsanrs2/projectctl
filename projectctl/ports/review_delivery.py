from __future__ import annotations

from typing import Protocol

from projectctl.schemas.delivery import ReviewReceipt, ReviewRequest


class ReviewDeliveryAdapter(Protocol):
    def reconcile(self, request: ReviewRequest) -> ReviewReceipt: ...

    def request_review(self, request: ReviewRequest) -> ReviewReceipt: ...
