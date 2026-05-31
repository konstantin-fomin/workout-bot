from typing import Any

from fastapi import FastAPI

from exercises import WORKOUTS


app = FastAPI(
    title="Workout Bot API",
    description="Local/test API for Swagger and Postman practice.",
    version="0.1.0",
)


def normalize_exercises() -> list[dict[str, Any]]:
    exercises: list[dict[str, Any]] = []

    for day_number, day_data in WORKOUTS.items():
        for exercise in day_data.get("exercises", []):
            exercises.append(
                {
                    "day_number": day_number,
                    "id": exercise.get("id"),
                    "name": exercise.get("name"),
                    "default_weight": exercise.get("default_weight"),
                    "weight_unit": exercise.get("weight_unit"),
                    "sets": exercise.get("sets", []),
                    "rest_seconds": exercise.get("rest_seconds"),
                    "tip": exercise.get("tip"),
                }
            )

    return exercises


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "workout-bot-api"}


@app.get("/exercises")
async def get_exercises() -> list[dict[str, Any]]:
    return normalize_exercises()
