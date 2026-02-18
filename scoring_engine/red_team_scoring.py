from sqlalchemy import func

from scoring_engine.db import db
from scoring_engine.models.flag import RedFlagSubmission
from scoring_engine.models.score_adjustment import ScoreAdjustment
from scoring_engine.models.setting import Setting


DEFAULT_RED_FLAG_SUBMISSION_PENALTY = 10


def get_red_flag_submission_penalty():
    setting = Setting.get_setting("red_team_flag_submission_penalty")
    if setting is None:
        return DEFAULT_RED_FLAG_SUBMISSION_PENALTY
    try:
        return int(setting.value)
    except (TypeError, ValueError):
        return DEFAULT_RED_FLAG_SUBMISSION_PENALTY


def get_blue_team_penalty_points():
    penalties = (
        db.session.query(
            RedFlagSubmission.target_team_id,
            func.coalesce(func.sum(RedFlagSubmission.points), 0),
        )
        .group_by(RedFlagSubmission.target_team_id)
        .all()
    )
    return {team_id: int(points) for team_id, points in penalties}


def get_blue_team_manual_adjustment_points():
    adjustments = (
        db.session.query(
            ScoreAdjustment.target_team_id,
            func.coalesce(func.sum(ScoreAdjustment.points), 0),
        )
        .group_by(ScoreAdjustment.target_team_id)
        .all()
    )
    return {team_id: int(points) for team_id, points in adjustments}
