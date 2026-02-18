from datetime import datetime, timedelta, timezone

from flask import jsonify, request
from flask_login import current_user, login_required
from dateutil.parser import parse as parse_datetime
from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.expression import and_, or_

from scoring_engine.cache import cache
from scoring_engine.cache_helper import update_flags_data, update_scoreboard_data, update_team_stats
from scoring_engine.db import db
from scoring_engine.models.flag import (
    Flag,
    FlagTypeEnum,
    Perm,
    Platform,
    RedFlagSubmission,
    Solve,
)
from scoring_engine.models.service import Service
from scoring_engine.models.setting import Setting
from scoring_engine.models.score_adjustment import ScoreAdjustment
from scoring_engine.models.team import Team
from scoring_engine.red_team_scoring import get_red_flag_submission_penalty

from . import make_cache_key, mod


def _parse_datetime_input(value):
    if not value:
        return None
    try:
        parsed = parse_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_flag_token(flag_obj):
    if not isinstance(flag_obj.data, dict):
        return None
    token = flag_obj.data.get("flag")
    if token:
        return str(token).strip()
    content_token = flag_obj.data.get("content")
    if content_token:
        return str(content_token).strip()
    return None


@mod.route("/api/flags")
@login_required
@cache.cached(make_cache_key=make_cache_key)
def api_flags():
    team = db.session.get(Team, current_user.team.id)
    if team is None or not current_user.team == team or not (current_user.is_red_team or current_user.is_white_team):
        return jsonify({"status": "Unauthorized"}), 403

    # Use naive UTC time for SQLAlchemy filter comparison (databases may not support timezones)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    early = now + timedelta(minutes=int(Setting.get_setting("agent_show_flag_early_mins").value))
    flags = (
        db.session.query(Flag)
        .filter(and_(early > Flag.start_time, now < Flag.end_time, Flag.dummy == False))
        .order_by(Flag.start_time)
        .all()
    )

    # White team can see all active flags.
    # Red team can only see flags that have already been submitted by their team.
    if current_user.is_red_team:
        submitted_flag_ids = {
            row.flag_id
            for row in db.session.query(RedFlagSubmission.flag_id)
            .filter(RedFlagSubmission.submitted_by_team_id == current_user.team.id)
            .all()
        }
        flags = [flag for flag in flags if flag.id in submitted_flag_ids]

    # Serialize flags and include localized times
    data = [
        {
            "id": f.id,
            "flag": _get_flag_token(f),
            "content": f.data.get("content"),
        }
        for f in flags
    ]

    return jsonify(data=data)


@mod.route("/api/flags/add", methods=["POST"])
@login_required
def api_flags_add():
    if not current_user.is_white_team:
        return jsonify({"error": "Incorrect permissions"}), 403

    payload = request.get_json(silent=True) or request.form
    content = (payload.get("content") or "").strip()
    dummy_raw = str(payload.get("dummy", "false")).strip().lower()

    if not content:
        return jsonify({"error": "content is required"}), 400

    start_time = _parse_datetime_input(payload.get("start_time")) or datetime.now(
        timezone.utc
    )
    end_time = _parse_datetime_input(payload.get("end_time")) or (
        start_time + timedelta(hours=3)
    )
    if end_time <= start_time:
        return jsonify({"error": "end_time must be after start_time"}), 400

    dummy = dummy_raw in {"true", "1", "yes", "on"}
    new_flag = Flag(
        type=FlagTypeEnum.file,
        platform=Platform.nix,
        perm=Perm.user,
        data={
            "content": content,
        },
        start_time=start_time,
        end_time=end_time,
        dummy=dummy,
    )
    db.session.add(new_flag)
    db.session.commit()

    update_flags_data()

    return jsonify({"status": "ok", "flag_id": new_flag.id})


@mod.route("/api/flags/adjust_score", methods=["POST"])
@login_required
def api_flags_adjust_score():
    if not current_user.is_white_team:
        return jsonify({"error": "Incorrect permissions"}), 403

    payload = request.get_json(silent=True) or request.form
    team_id = payload.get("team_id")
    points = payload.get("points")
    reason = (payload.get("reason") or "").strip()

    if team_id is None or points is None:
        return jsonify({"error": "team_id and points are required"}), 400

    try:
        team_id = int(team_id)
        points = int(points)
    except (TypeError, ValueError):
        return jsonify({"error": "team_id and points must be integers"}), 400

    target_team = db.session.get(Team, team_id)
    if target_team is None or not target_team.is_blue_team:
        return jsonify({"error": "target team must be a blue team"}), 400

    adjustment = ScoreAdjustment(
        target_team_id=target_team.id,
        adjusted_by_team_id=current_user.team.id,
        adjusted_by_user_id=current_user.id,
        points=points,
        reason=reason if reason else None,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(adjustment)
    db.session.commit()

    update_scoreboard_data()
    update_team_stats(target_team.id)

    return jsonify(
        {
            "status": "ok",
            "team_id": target_team.id,
            "points": points,
            "reason": reason,
        }
    )


@mod.route("/api/flags/submit", methods=["POST"])
@login_required
def api_flags_submit():
    if not current_user.is_red_team:
        return jsonify({"error": "Incorrect permissions"}), 403

    payload = request.get_json(silent=True) or request.form
    flag_id = payload.get("flag_id")
    submitted_flag_value = (
        payload.get("content")
        or payload.get("flag")
        or payload.get("flag_value")
        or payload.get("submitted_flag")
    )
    team_id = payload.get("team_id")

    if not team_id:
        return jsonify({"error": "team_id is required"}), 400
    if not flag_id and not submitted_flag_value:
        return jsonify({"error": "flag_id or submitted flag value is required"}), 400

    try:
        team_id = int(team_id)
    except (TypeError, ValueError):
        return jsonify({"error": "team_id must be an integer"}), 400

    target_team = db.session.get(Team, team_id)
    if target_team is None or not target_team.is_blue_team:
        return jsonify({"error": "target team must be a blue team"}), 400

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    flag = None
    if flag_id:
        flag = db.session.get(Flag, flag_id)
    else:
        submitted_flag_value = str(submitted_flag_value).strip()
        candidate_flags = (
            db.session.query(Flag)
            .filter(Flag.dummy == False)
            .all()
        )
        for candidate in candidate_flags:
            if not (candidate.start_time <= now <= candidate.end_time):
                continue
            token = _get_flag_token(candidate)
            if token and token == submitted_flag_value:
                flag = candidate
                break

    if flag is None:
        return jsonify({"error": "flag not found"}), 404
    if flag.dummy or not (flag.start_time <= now <= flag.end_time):
        return jsonify({"error": "flag is not currently active"}), 400

    points = get_red_flag_submission_penalty()
    submission = RedFlagSubmission(
        flag_id=flag.id,
        target_team_id=target_team.id,
        submitted_by_team_id=current_user.team.id,
        submitted_by_user_id=current_user.id,
        points=points,
        submitted_at=datetime.now(timezone.utc),
    )
    db.session.add(submission)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"error": "flag already submitted for this blue team"}), 409

    update_scoreboard_data()
    update_team_stats(target_team.id)
    update_flags_data()

    return jsonify(
        {
            "status": "ok",
            "flag_id": flag.id,
            "team_id": target_team.id,
            "points_deducted": points,
        }
    )


@mod.route("/api/flags/solves")
@login_required
@cache.cached(make_cache_key=make_cache_key)
def api_flags_solves():
    if not current_user.is_red_team and not current_user.is_white_team:
        return jsonify({"status": "Unauthorized"}), 403

    # Get all flags and teams
    # Use naive UTC time for SQLAlchemy filter comparison (databases may not support timezones)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    active_flags = (
        db.session.query(Flag)
        .filter(and_(now > Flag.start_time, now < Flag.end_time, Flag.dummy == False))
        .order_by(Flag.start_time)
        .all()
    )
    active_flag_ids = [flag.id for flag in active_flags]

    # Flag Solve Status
    all_hosts = (
        db.session.query(
            Service.name.label("service_name"),
            Service.port,
            Service.team_id,
            Service.host,
            Team.name.label("team_name"),
            func.coalesce(Solve.id, None).label("solve_id"),
            func.coalesce(Flag.id, None).label("flag_id"),
            func.coalesce(Flag.perm, None).label("flag_perm"),
            func.coalesce(Flag.platform, None).label("flag_platform"),
        )
        .select_from(Service)
        .filter(Service.check_name == "AgentCheck")
        .outerjoin(
            Solve,
            and_(Solve.host == Service.host, Solve.team_id == Service.team_id, Solve.flag_id.in_(active_flag_ids)),
        )
        .outerjoin(Flag, Flag.id == Solve.flag_id)
        .outerjoin(Team, Team.id == Service.team_id)
        .order_by(Service.name, Service.team_id)
        .all()
    )

    data = {}
    rows = []
    columns = ["Team"]

    for item in all_hosts:
        if item.service_name not in columns:
            columns.append(item.service_name)
        if not data.get(item.team_name):
            data[item.team_name] = {}
        if not data[item.team_name].get(item.service_name):
            data[item.team_name][item.service_name] = [0, 0]
        if item.solve_id:
            if item.flag_perm.value == "user":
                data[item.team_name][item.service_name][0] = 1
            else:
                data[item.team_name][item.service_name][1] = 1

    for key, val in data.items():
        new_row = [key]
        for host in val.values():
            new_row.append(host)
        rows.append(new_row)

    return jsonify(data={"columns": columns, "rows": rows})


@mod.route("/api/flags/totals")
@login_required
@cache.cached(make_cache_key=make_cache_key)
def api_flags_totals():
    if not current_user.is_red_team and not current_user.is_white_team:
        return jsonify({"status": "Unauthorized"}), 403

    totals = {}  # [ Team0, Win Score, Nix Score ]
    blue_teams = db.session.query(Team).filter(Team.color == "Blue").order_by(Team.id).all()
    for blue_team in blue_teams:
        totals[blue_team.name] = [blue_team.name, 0, 0]

    for platform_enum in [Platform.windows, Platform.nix]:
        # Subquery 1: Determine permission level per (team, host, start_time)
        # If root perm exists in the group, level is "root"; otherwise "user"
        subquery1 = (
            db.session.query(
                Solve.team_id,
                Solve.host,
                case(
                    (func.max(case((Flag.perm == Perm.root, 1), else_=0)) == 1, "root"),
                    else_="user",
                ).label("level"),
            )
            .join(Flag, Flag.id == Solve.flag_id)
            .filter(Flag.platform == platform_enum)
            .group_by(Solve.team_id, Flag.platform, Solve.host, Flag.start_time)
            .subquery()
        )

        # Subquery 2: Compute red_amt based on level
        subquery2 = (
            db.session.query(
                (subquery1.c.team_id).label("BlueTeamId"),
                case(
                    (subquery1.c.level == "user", 0.5 * func.count()),
                    else_=1 * func.count(),
                ).label("red_amt"),
            )
            .group_by(subquery1.c.team_id, subquery1.c.level)
            .order_by(subquery1.c.team_id, subquery1.c.level.desc())
            .subquery()
        )

        # Final Query: Sum red_amt per BlueTeamId
        final_query = (
            db.session.query(
                Team.name.label("BlueTeam"),
                func.sum(subquery2.c.red_amt).label("RedScore"),
            )
            .join(Team, subquery2.c.BlueTeamId == Team.id)
            .group_by(subquery2.c.BlueTeamId)
            .order_by(func.sum(subquery2.c.red_amt))
        )

        # Execute Query
        results = final_query.all()

        for row in results:
            if platform_enum == Platform.windows:
                totals[row.BlueTeam][1] = row.RedScore
            elif platform_enum == Platform.nix:
                totals[row.BlueTeam][2] = row.RedScore

    data = []
    for team in totals.values():
        data.append({"team": team[0], "win_score": team[1], "nix_score": team[2], "total_score": team[1] + team[2]})

    return jsonify(data=data)
