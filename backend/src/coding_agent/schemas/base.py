"""所有 HTTP Schema 共用的基础模型。"""

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """拒绝未声明字段的所有 HTTP 请求、响应模型基类。"""

    # 禁止静默忽略客户端拼错或服务端意外增加的字段。
    model_config = ConfigDict(extra="forbid")


__all__ = ["ApiModel"]
