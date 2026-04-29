from enum import Enum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String


class Base(DeclarativeBase):
    pass

class FileStatus(Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    SUCCESS = "success"
    FAILED = "failed"

class File(Base):
    """File in index"""
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(primary_key=True)
    filepath: Mapped[str] = mapped_column(unique=True)
    file_hash: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(default=FileStatus.PENDING.value)
    message_id: Mapped[int | None] = mapped_column(default=None)
