import datetime

from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ChatRequest(_message.Message):
    __slots__ = ("query", "current_timestamp", "k", "session_id", "user_id", "access_token")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    CURRENT_TIMESTAMP_FIELD_NUMBER: _ClassVar[int]
    K_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    USER_ID_FIELD_NUMBER: _ClassVar[int]
    ACCESS_TOKEN_FIELD_NUMBER: _ClassVar[int]
    query: str
    current_timestamp: _timestamp_pb2.Timestamp
    k: int
    session_id: str
    user_id: str
    access_token: str
    def __init__(self, query: _Optional[str] = ..., current_timestamp: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., k: _Optional[int] = ..., session_id: _Optional[str] = ..., user_id: _Optional[str] = ..., access_token: _Optional[str] = ...) -> None: ...

class ChatResponse(_message.Message):
    __slots__ = ("token", "is_final", "sources")
    TOKEN_FIELD_NUMBER: _ClassVar[int]
    IS_FINAL_FIELD_NUMBER: _ClassVar[int]
    SOURCES_FIELD_NUMBER: _ClassVar[int]
    token: str
    is_final: bool
    sources: _containers.RepeatedCompositeFieldContainer[SourceDocument]
    def __init__(self, token: _Optional[str] = ..., is_final: bool = ..., sources: _Optional[_Iterable[_Union[SourceDocument, _Mapping]]] = ...) -> None: ...

class SourceDocument(_message.Message):
    __slots__ = ("title", "uri", "score")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    URI_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    title: str
    uri: str
    score: float
    def __init__(self, title: _Optional[str] = ..., uri: _Optional[str] = ..., score: _Optional[float] = ...) -> None: ...

class IndexDocumentsRequest(_message.Message):
    __slots__ = ("drive_folder_id", "access_token")
    DRIVE_FOLDER_ID_FIELD_NUMBER: _ClassVar[int]
    ACCESS_TOKEN_FIELD_NUMBER: _ClassVar[int]
    drive_folder_id: str
    access_token: str
    def __init__(self, drive_folder_id: _Optional[str] = ..., access_token: _Optional[str] = ...) -> None: ...

class IndexDocumentsResponse(_message.Message):
    __slots__ = ("chunk_count", "files", "message")
    CHUNK_COUNT_FIELD_NUMBER: _ClassVar[int]
    FILES_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    chunk_count: int
    files: _containers.RepeatedScalarFieldContainer[str]
    message: str
    def __init__(self, chunk_count: _Optional[int] = ..., files: _Optional[_Iterable[str]] = ..., message: _Optional[str] = ...) -> None: ...
