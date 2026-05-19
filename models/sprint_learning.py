from sqlalchemy import Column, String, Text, DateTime
from .base import Base

class SprintLearning(Base):
    __tablename__ = 'sprint_learnings'
    
    project_id = Column(String(255), nullable=False)
    sprint_id = Column(String(255), nullable=False)
    learning_type = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)