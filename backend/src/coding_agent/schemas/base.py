"""所有 HTTP Schema 共用的基础模型。"""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


__all__ = ["ApiModel"]
