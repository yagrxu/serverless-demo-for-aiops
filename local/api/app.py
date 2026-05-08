"""Local-dev HTTP wrapper around the Lambda handlers.

The CDK Lambdas are plain functions that take an API-Gateway-shaped event
and return an API-Gateway-shaped response. This FastAPI app replays each
incoming request as that event shape so the *same handler code* runs
locally against DynamoDB Local.

The wrapper lives in `local/` so production Lambda packages stay clean.
"""
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

# Make the Lambda source importable.
# In Docker the lambda code is bind-mounted at /app/lambda; outside Docker
# we walk up from local/api/app.py to the repo root.
_here = Path(__file__).resolve()
_docker_lambda = _here.parent / "lambda"
LAMBDA_ROOT = _docker_lambda if _docker_lambda.is_dir() else _here.parents[2] / "cdk" / "lambda"
for svc in ("cat-profile", "device", "feeding", "health"):
    sys.path.insert(0, str(LAMBDA_ROOT / svc))

# Import each service's handler under a distinct alias.
import importlib.util


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


cat_handler = _load("cat_handler", LAMBDA_ROOT / "cat-profile" / "handler.py").lambda_handler
device_handler = _load("device_handler", LAMBDA_ROOT / "device" / "handler.py").lambda_handler
feeding_handler = _load("feeding_handler", LAMBDA_ROOT / "feeding" / "handler.py").lambda_handler
health_handler = _load("health_handler", LAMBDA_ROOT / "health" / "handler.py").lambda_handler


app = FastAPI(title="cat-demo local API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _invoke(handler, resource: str, method: str, request: Request, path_params=None):
    body_bytes = await request.body()
    event = {
        "resource": resource,
        "httpMethod": method,
        "pathParameters": path_params or None,
        "queryStringParameters": dict(request.query_params) or None,
        "headers": dict(request.headers),
        "body": body_bytes.decode() if body_bytes else None,
        "isBase64Encoded": False,
    }
    result = handler(event, None)
    return Response(
        content=result.get("body", ""),
        status_code=result.get("statusCode", 200),
        media_type=result.get("headers", {}).get("Content-Type", "application/json"),
    )


# --- cats ---
@app.get("/cats")
async def list_cats(request: Request):
    return await _invoke(cat_handler, "/cats", "GET", request)

@app.post("/cats")
async def create_cat(request: Request):
    return await _invoke(cat_handler, "/cats", "POST", request)

@app.get("/cats/lookup")
async def lookup_cat(request: Request):
    return await _invoke(cat_handler, "/cats/lookup", "GET", request)

@app.get("/cats/{id}")
async def get_cat(id: str, request: Request):
    return await _invoke(cat_handler, "/cats/{id}", "GET", request, {"id": id})


# --- devices ---
@app.get("/devices")
async def list_devices(request: Request):
    return await _invoke(device_handler, "/devices", "GET", request)

@app.get("/devices/{id}")
async def get_device(id: str, request: Request):
    return await _invoke(device_handler, "/devices/{id}", "GET", request, {"id": id})

@app.post("/devices/{id}/commands")
async def device_command(id: str, request: Request):
    return await _invoke(device_handler, "/devices/{id}/commands", "POST", request, {"id": id})

@app.post("/devices/{id}/telemetry")
async def device_telemetry(id: str, request: Request):
    return await _invoke(device_handler, "/devices/{id}/telemetry", "POST", request, {"id": id})


# --- feedings ---
@app.get("/feedings")
async def list_feedings(request: Request):
    return await _invoke(feeding_handler, "/feedings", "GET", request)

@app.post("/feedings")
async def create_feeding(request: Request):
    return await _invoke(feeding_handler, "/feedings", "POST", request)


# --- health ---
@app.get("/health/{cat_id}")
async def health_metrics(cat_id: str, request: Request):
    return await _invoke(health_handler, "/health/{cat_id}", "GET", request, {"cat_id": cat_id})

@app.get("/health/{cat_id}/alerts")
async def health_alerts(cat_id: str, request: Request):
    return await _invoke(health_handler, "/health/{cat_id}/alerts", "GET", request, {"cat_id": cat_id})


@app.get("/_ping")
def ping():
    return {"ok": True, "ddb": os.environ.get("DDB_ENDPOINT", "")}
