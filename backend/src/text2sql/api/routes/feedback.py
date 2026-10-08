"""POST /v1/feedback: rate an answer (stored in app.feedback)."""

import uuid

from fastapi import APIRouter
from pydantic import BaseModel, Field

from text2sql.api.dependencies import LimitedUserDep, ServicesDep
from text2sql.api.errors import ApiError
from text2sql.observability.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/v1", tags=["feedback"])


class FeedbackIn(BaseModel):
    """A rating for one answer; resubmitting replaces the previous rating."""

    query_id: uuid.UUID
    rating: int = Field(ge=1, le=5, description="1 (bad) to 5 (good).")
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    """Stored feedback."""

    feedback_id: int


@router.post("/feedback", status_code=201, responses={404: {}})
async def feedback(body: FeedbackIn, user: LimitedUserDep, services: ServicesDep) -> FeedbackOut:
    """Only the user who asked a question can rate its answer."""
    owner = await services.store.query_owner(body.query_id)
    if owner != user.user_id:
        # Same response for "missing" and "someone else's": query ids are not enumerable.
        raise ApiError(404, "not_found", "No such query.")
    comment = body.comment.strip() if body.comment else None
    feedback_id = await services.store.save_feedback(
        body.query_id, user.user_id, body.rating, comment or None
    )
    log.info("feedback_saved", query_id=str(body.query_id), rating=body.rating)
    return FeedbackOut(feedback_id=feedback_id)
