from typing import List, Optional

from pydantic import BaseModel, Field, StrictBool, StrictInt


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class RtspRequest(BaseModel):
    name: str = Field(default="", max_length=80)
    host: str = Field(max_length=253)
    port: int = 554
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=256)
    path: str = Field(default="", max_length=200)


class CameraCredentials(BaseModel):
    username: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=256)


class LocalRequest(BaseModel):
    ref: str = Field(max_length=300)
    name: str = Field(default="", max_length=80)


class ZoneIn(BaseModel):
    id: Optional[int] = None
    name: str = Field(max_length=80)
    kind: str = Field(max_length=20)
    shape: str = Field(default="poly", max_length=20)
    angle: float = 0.0
    margin: Optional[float] = None
    points: List[List[float]] = Field(max_length=64)


class ZonesRequest(BaseModel):
    zones: List[ZoneIn] = Field(max_length=200)


class RecognitionRequest(BaseModel):
    enabled: StrictBool = True
    classes: List[StrictInt] = Field(default_factory=list, max_length=80)
