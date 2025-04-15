import re
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, validates
from models.base import Base

class Share(Base):
    __tablename__ = 'share'

    id = Column(Integer, primary_key=True)
    customer = Column(String(50), nullable=False)
    folder_name = Column(String(100), unique=False, nullable=False)
    quota = Column(Integer, nullable=False)
    server = Column(String(100), nullable=False)
    protocol = Column(String(50), nullable=True)
    owner = Column(String(100), nullable=False)
    users = Column(String(200), nullable=False)
    index = Column(Integer, nullable=False, default=-1)
    permission = Column(String(50), nullable=False)
    parent_id = Column(Integer, ForeignKey('share.id'), nullable=True)
    parent = relationship('Share', remote_side=[id], backref='children')
    can_fix = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint('index', 'folder_name', name='unique_acl_constraint'),
    )

    @validates('quota')
    def validate_int(self, key, value):
        value = int(value)
        if value < 0:
            raise ValueError("Quota must be a positive number or 0 to unset")
        return value

    @validates('folder_name', 'owner')
    def validate_posix(self, key, value):
        value = str(value)
        if not re.match(r'^[a-zA-Z0-9._/-]*$', value):
            raise ValueError(f"{key} must be a valid POSIX string")
        return value

    @validates('users', 'permission', 'protocol')
    def validate_unique_set(self, key, value):
        if isinstance(value, str):
            value = set(value.split(','))
        elif isinstance(value, list):
            value = set(value)
        elif not isinstance(value, set):
            raise ValueError(f"{key} must be a string, set or a list")
        value.discard(None)
        value.discard('')
        return ','.join(sorted(value))