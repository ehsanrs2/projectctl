from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


SchemaVersion = Annotated[int, Field(ge=1)]
Ratio = Annotated[float, Field(ge=0.0, le=1.0)]
Priority = Annotated[int, Field(ge=0, le=10)]
Signal5 = Annotated[int, Field(ge=0, le=5)]


class ProjectCtlModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )
