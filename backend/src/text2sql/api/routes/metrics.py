"""GET /metrics: Prometheus exposition of the pipeline metrics (404 when disabled).

Unauthenticated, like the health probes, for the scraper. The API listens on 127.0.0.1 only
(compose); behind a public proxy, do not route ``/metrics`` outside the private network.
"""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST

from text2sql.api.dependencies import ServicesDep
from text2sql.api.errors import ApiError

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=Response, responses={404: {}})
async def metrics(services: ServicesDep) -> Response:
    """Counters and histograms in the Prometheus text format."""
    pipeline = services.observer.metrics
    if pipeline is None:
        raise ApiError(404, "not_found", "Metrics are disabled.")
    return Response(pipeline.render(), media_type=CONTENT_TYPE_LATEST)
