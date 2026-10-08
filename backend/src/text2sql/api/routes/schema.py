"""GET /v1/schema: what users can ask about, for the UI."""

from fastapi import APIRouter
from pydantic import BaseModel

from text2sql.api.dependencies import LimitedUserDep, ServicesDep

router = APIRouter(prefix="/v1", tags=["schema"])


class ColumnOut(BaseModel):
    """A readable column."""

    name: str
    type: str
    description: str


class TableOut(BaseModel):
    """A queryable table or view."""

    name: str
    kind: str
    description: str
    columns: list[ColumnOut]


class SchemaOut(BaseModel):
    """Relations and columns the query role can read.

    No personal-data columns, no sample values, no internal tables.
    """

    tables: list[TableOut]


@router.get("/schema")
async def schema(user: LimitedUserDep, services: ServicesDep) -> SchemaOut:
    """Tables, views and their readable columns with business descriptions."""
    del user
    tables = await services.store.schema_summary()
    return SchemaOut(
        tables=[
            TableOut(
                name=t.name,
                kind=t.kind,
                description=t.description,
                columns=[
                    ColumnOut(name=c.name, type=c.type, description=c.description)
                    for c in t.columns
                ],
            )
            for t in tables
        ]
    )
