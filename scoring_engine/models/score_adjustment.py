from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from scoring_engine.models.base import Base


class ScoreAdjustment(Base):
    __tablename__ = "score_adjustments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    adjusted_by_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    adjusted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    points = Column(Integer, nullable=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)

    target_team = relationship("Team", foreign_keys=[target_team_id], lazy="joined")
    adjusted_by_team = relationship("Team", foreign_keys=[adjusted_by_team_id], lazy="joined")
