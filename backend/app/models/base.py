"""所有 SQLAlchemy 模型共用的声明式基类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有应用模型的基类。"""
