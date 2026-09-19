"""Garmin Coach plan curation, pinned to a real adaptive-plan payload.

The fixture below is the shape Garmin actually returned for an enrolled ATP
plan on 2026-09-19. Two things in it are load-bearing:

  * ``planName`` is None. Garmin does not name adaptive plans.
  * there is no ``trainingType`` key. Upstream read only that key, so it
    resolved to None, was dropped by the "strip None" filter, and the entire
    trainingPlanDetailsDTO -- the race goal included -- went with it. The tool
    could return nothing but an id and a classification.

Also covers get_gear_activities, whose tests previously shared a file with the
three training-plan tools removed in the same change.
"""
import json

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_mcp import gear_management, workouts
from garmin_mcp.client_resolver import set_global_client

# Verbatim shape of a live adaptive plan (values are this fork's own account).
_LIVE_ATP_PLAN = {
    "planName": None,
    "trainingPlanId": 1789330190,
    "trainingPlanClassification": "ATP",
    "trainingPlanDetailsDTO": {
        "athletePlanId": 1789330190,
        "athleteRace": {
            "raceDay": "2026-11-26",
            "raceName": "River Vale 5K",
            "raceUrl": None,
        },
        "remainingAtpWorkoutsForWeek": 1,
        "workoutsPerWeek": 3,
        "registrationDate": "2026-09-13T20:09:50.515",
        "planCompleted": False,
        "workoutPlanTypeId": 1,
    },
    "workoutScheduleSummaries": [
        {
            "calendarDate": "2026-09-19",
            "scheduledWorkoutId": 1780843621,
            "workoutId": 1701453828,
            "workoutName": "Run Walk Run®",
            "sportType": {"sportTypeKey": "running"},
            "completed": False,
        }
    ],
}


def _app(client):
    workouts.configure(client)
    set_global_client(client)
    return workouts.register_tools(FastMCP("t"))


def _graphql(plans):
    return {"data": {"trainingPlanScalar": {"trainingPlanWorkoutScheduleDTOS": plans}}}


async def _plan(app, client):
    client.query_garmin_graphql.return_value = _graphql([_LIVE_ATP_PLAN])
    text = (await app.call_tool("get_garmin_coach_workouts",
                                {"calendar_date": "2026-09-19"}))[0][0].text
    return json.loads(text)["plans"][0]


@pytest.mark.asyncio
async def test_race_goal_survives_curation(mock_garmin_client):
    """The goal is the point of an adaptive plan and was being thrown away."""
    plan = await _plan(_app(mock_garmin_client), mock_garmin_client)
    assert plan["race_name"] == "River Vale 5K"
    assert plan["race_day"] == "2026-11-26"


@pytest.mark.asyncio
async def test_plan_shape_survives_curation(mock_garmin_client):
    plan = await _plan(_app(mock_garmin_client), mock_garmin_client)
    assert plan["workouts_per_week"] == 3
    assert plan["remaining_workouts_this_week"] == 1
    assert plan["registration_date"].startswith("2026-09-13")
    assert plan["plan_completed"] is False, "False must survive the strip-None filter"


@pytest.mark.asyncio
async def test_identity_fields_still_present(mock_garmin_client):
    plan = await _plan(_app(mock_garmin_client), mock_garmin_client)
    assert plan["training_plan_id"] == 1789330190
    assert plan["classification"] == "ATP"
    # Garmin sends no name for adaptive plans; absent beats a null.
    assert "name" not in plan


@pytest.mark.asyncio
async def test_absent_details_do_not_crash_or_emit_nulls(mock_garmin_client):
    """A plan family without the DTO must degrade, not fail."""
    bare = {"trainingPlanId": 42, "trainingPlanClassification": "PHASED",
            "workoutScheduleSummaries": []}
    mock_garmin_client.query_garmin_graphql.return_value = _graphql([bare])
    text = (await _app(mock_garmin_client).call_tool(
        "get_garmin_coach_workouts", {"calendar_date": "2026-09-19"}))[0][0].text
    if "No training plan workouts" not in text:
        plan = json.loads(text)["plans"][0]
        assert plan["training_plan_id"] == 42
        assert not any(k.startswith("race_") for k in plan)


@pytest.mark.asyncio
async def test_removed_training_plan_tools_are_gone(mock_garmin_client):
    """They were built on trainingplan-service REST, which returns empty or 404.

    Re-adding them on that path would look like a feature and behave like a bug.
    """
    names = {t.name for t in _app(mock_garmin_client)._tool_manager.list_tools()}
    assert not names & {
        "get_training_plans",
        "get_training_plan_details",
        "get_adaptive_training_plan_details",
    }


# ─── get_gear_activities (rehomed from the deleted file) ──────────────────

@pytest.mark.asyncio
async def test_gear_activities_totals_distance(mock_garmin_client):
    gear_management.configure(mock_garmin_client)
    set_global_client(mock_garmin_client)
    app = gear_management.register_tools(FastMCP("g"))
    mock_garmin_client.get_gear_activities.return_value = [
        {"activityId": 1, "distance": 2864.6, "activityType": {"typeKey": "walking"}},
        {"activityId": 2, "distance": 788.6, "activityType": {"typeKey": "walking"}},
    ]
    payload = json.loads(
        (await app.call_tool("get_gear_activities", {"gear_uuid": "abc"}))[0][0].text
    )
    assert payload["activity_count"] == 2
    assert payload["total_distance_m"] == pytest.approx(3653.2)
    mock_garmin_client.get_gear_activities.assert_called_once_with("abc", limit=1000)


@pytest.mark.asyncio
async def test_gear_activities_tolerates_null_distance(mock_garmin_client):
    gear_management.configure(mock_garmin_client)
    set_global_client(mock_garmin_client)
    app = gear_management.register_tools(FastMCP("g"))
    mock_garmin_client.get_gear_activities.return_value = [
        {"activityId": 1, "distance": None}, {"activityId": 2, "distance": 100.0},
    ]
    payload = json.loads(
        (await app.call_tool("get_gear_activities", {"gear_uuid": "g"}))[0][0].text
    )
    assert payload["total_distance_m"] == 100.0
