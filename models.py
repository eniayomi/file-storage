from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from passlib.context import CryptContext

Base = declarative_base()

# Password hashing configuration
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class Link(Base):
    __tablename__ = 'links'

    id = Column(Integer, primary_key=True, nullable=False)
    custom_link = Column(String(255), unique=True, nullable=False, index=True)
    file_path = Column(Text, nullable=False)
    is_public = Column(Boolean, default=False, nullable=False)
    file_password = Column(String, nullable=True)
    created_at = Column(
        DateTime, 
        server_default=func.now(),
        nullable=False
    )

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password for storing."""
        return pwd_context.hash(password) if password else None

    def verify_password(self, plain_password: str) -> bool:
        """Verify a stored password against one provided by user"""
        if not self.file_password or not plain_password:
            return False
        return pwd_context.verify(plain_password, self.file_password)

    def __repr__(self):
        return f"<Link(custom_link='{self.custom_link}', is_public={self.is_public})>"

# Optional: Add migrations table model if you want to track it with SQLAlchemy
class Migration(Base):
    __tablename__ = 'alembic_version'
    
    version_num = Column(String(32), primary_key=True)

    def __repr__(self):
        return f"<Migration(version='{self.version_num}')>" 