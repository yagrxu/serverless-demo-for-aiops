#!/usr/bin/env python3
"""Seed 6 months of history data for the cat-care demo.

Usage:
  python scripts/seed/seed-history.py [--endpoint http://localhost:8001] [--region us-east-1]

Idempotent: uses deterministic IDs so re-runs overwrite, not duplicate.
Includes subtle anomaly records per cat for frontier-model reasoning tests.
"""
import argparse
import random
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

CATS = [
    {"cat_id": "hotpot", "name": "火锅", "household_id": "household-1", "breed": "英国短毛猫（矮脚）", "weight_kg": 4.2},
    {"cat_id": "bbq", "name": "烧烤", "household_id": "household-1", "breed": "英国短毛猫", "weight_kg": 5.1},
]

DEVICES = [
    {"device_id": "feeder-01", "cat_id": "hotpot", "type": "auto_feeder", "status": "online"},
    {"device_id": "feeder-02", "cat_id": "bbq", "type": "auto_feeder", "status": "online"},
    {"device_id": "fountain-01", "cat_id": "hotpot", "type": "water_fountain", "status": "online"},
]

VET_RECORDS_SEED = [
    {"cat_id": "hotpot", "record_id": "seed-vet-001", "record_type": "dietary_restriction",
     "effective_from": "2026-06-01T00:00:00Z", "effective_until": None,
     "details": {"restriction": "low_protein", "reason": "kidney checkup", "max_protein_pct": 30},
     "vet_signature": "Dr. Wang"},
    {"cat_id": "bbq", "record_id": "seed-vet-002", "record_type": "weight_target",
     "effective_from": "2026-05-15T00:00:00Z", "effective_until": None,
     "details": {"target_kg": 4.8, "current_kg": 5.1, "plan": "reduce dry food by 20%"},
     "vet_signature": "Dr. Wang"},
    {"cat_id": "hotpot", "record_id": "seed-vet-003", "record_type": "allergy",
     "effective_from": "2026-01-10T00:00:00Z", "effective_until": None,
     "details": {"allergen": "chicken", "severity": "mild", "alternative": "fish-based"},
     "vet_signature": "Dr. Li"},
]


def _dec(v):
    return Decimal(str(v)) if isinstance(v, float) else v


def seed_cat_profiles(table):
    for cat in CATS:
        table.put_item(Item={k: _dec(v) for k, v in cat.items()})
    print(f"  Seeded {len(CATS)} cat profiles")


def seed_devices(table):
    for d in DEVICES:
        d_copy = {**d, "last_seen": "2026-06-22T00:00:00Z"}
        table.put_item(Item=d_copy)
    print(f"  Seeded {len(DEVICES)} devices")


def seed_feedings(table, months=6):
    """Seed feeding events. One anomaly per cat: negative grams for hotpot, duplicate ts for bbq."""
    now = datetime.now(timezone.utc)
    count = 0
    for cat in CATS:
        cat_id = cat["cat_id"]
        for day_offset in range(months * 30):
            day = now - timedelta(days=day_offset)
            # 2-3 feedings per day, some days sparse
            n_feedings = random.choice([2, 2, 3, 3, 3, 1]) if day_offset % 7 != 0 else random.choice([0, 1])
            for meal in range(n_feedings):
                hour = 7 + meal * 5 + random.randint(0, 2)
                ts = day.replace(hour=hour, minute=random.randint(0, 59), second=0).strftime("%Y-%m-%dT%H:%M:%SZ")
                food_type = "wet" if meal == 0 else "dry"
                amount = random.randint(30, 70) if food_type == "wet" else random.randint(20, 50)
                item = {
                    "cat_id": cat_id,
                    "ts": ts,
                    "food_type": food_type,
                    "amount_grams": amount,
                    "source": "auto_feeder",
                }
                table.put_item(Item=item)
                count += 1

        # Anomaly: negative grams for hotpot (day 45)
        if cat_id == "hotpot":
            anom_day = now - timedelta(days=45)
            table.put_item(Item={
                "cat_id": cat_id,
                "ts": anom_day.replace(hour=12, minute=0).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "food_type": "dry", "amount_grams": -50, "source": "manual",
            })
        # Anomaly: duplicate timestamp for bbq (day 30)
        if cat_id == "bbq":
            anom_day = now - timedelta(days=30)
            dup_ts = anom_day.replace(hour=8, minute=0).strftime("%Y-%m-%dT%H:%M:%SZ")
            for i in range(2):
                table.put_item(Item={
                    "cat_id": cat_id,
                    "ts": dup_ts if i == 0 else dup_ts[:-1] + "1Z",  # near-duplicate
                    "food_type": "wet", "amount_grams": 50, "source": "auto_feeder",
                })
    print(f"  Seeded {count}+ feeding events (with anomalies)")


def seed_health_metrics(table, months=6):
    """Seed weight + activity readings. Anomaly: 10x weight for hotpot."""
    now = datetime.now(timezone.utc)
    count = 0
    for cat in CATS:
        cat_id = cat["cat_id"]
        base_weight = cat["weight_kg"]
        for day_offset in range(0, months * 30, 3):  # every 3 days
            day = now - timedelta(days=day_offset)
            ts = day.replace(hour=9, minute=0).strftime("%Y-%m-%dT%H:%M:%SZ")
            weight = base_weight + random.uniform(-0.1, 0.1)
            item = {
                "cat_id": cat_id,
                "ts": ts,
                "weight_kg": _dec(round(weight, 2)),
                "activity_level": _dec(round(random.uniform(4, 8), 1)),
            }
            table.put_item(Item=item)
            count += 1

        # Anomaly: 10x weight reading for hotpot (day 60) — unit mix-up kg vs g
        if cat_id == "hotpot":
            anom_day = now - timedelta(days=60)
            table.put_item(Item={
                "cat_id": cat_id,
                "ts": anom_day.replace(hour=9, minute=30).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "weight_kg": _dec(42.0),  # 10x — looks like grams not kg
                "activity_level": _dec(6.0),
            })
    print(f"  Seeded {count}+ health metrics (with anomalies)")


def seed_telemetry(table, months=6):
    """Seed device telemetry. Anomaly: reading from offline window for fountain."""
    now = datetime.now(timezone.utc)
    count = 0
    for dev in DEVICES:
        for day_offset in range(0, months * 30, 2):
            day = now - timedelta(days=day_offset)
            ts = day.replace(hour=14, minute=random.randint(0, 59)).strftime("%Y-%m-%dT%H:%M:%SZ")
            item = {
                "device_id": dev["device_id"],
                "ts": ts,
                "kind": "telemetry",
                "metrics": {"battery_pct": _dec(random.randint(40, 100)), "wifi_rssi": _dec(random.randint(-70, -30))},
            }
            table.put_item(Item=item)
            count += 1

    # Anomaly: telemetry from offline window (fountain was offline 2am-6am, reading at 3am)
    anom_day = now - timedelta(days=20)
    table.put_item(Item={
        "device_id": "fountain-01",
        "ts": anom_day.replace(hour=3, minute=15).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": "telemetry",
        "metrics": {"water_level_ml": _dec(200), "battery_pct": _dec(85)},
    })
    print(f"  Seeded {count}+ telemetry records (with anomaly)")


def seed_vet_records(table):
    for rec in VET_RECORDS_SEED:
        table.put_item(Item=rec)
    print(f"  Seeded {len(VET_RECORDS_SEED)} vet records")


def main():
    parser = argparse.ArgumentParser(description="Seed demo history data")
    parser.add_argument("--endpoint", default=None, help="DDB endpoint (e.g. http://localhost:8001)")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--profile", default=None)
    args = parser.parse_args()

    kwargs = {"region_name": args.region}
    if args.endpoint:
        kwargs["endpoint_url"] = args.endpoint
    if args.profile:
        session = boto3.Session(profile_name=args.profile)
        ddb = session.resource("dynamodb", **kwargs)
    else:
        ddb = boto3.resource("dynamodb", **kwargs)

    random.seed(42)  # deterministic

    print("Seeding cat-care demo data...")
    seed_cat_profiles(ddb.Table(get_table("CatProfiles")))
    seed_devices(ddb.Table(get_table("Devices")))
    seed_feedings(ddb.Table(get_table("FeedingEvents")))
    seed_health_metrics(ddb.Table(get_table("HealthMetrics")))
    seed_telemetry(ddb.Table(get_table("DeviceTelemetry")))
    seed_vet_records(ddb.Table(get_table("VetRecords")))
    print("Done!")


def get_table(logical_name: str) -> str:
    """Map logical name to actual table name. Override with env vars if needed."""
    import os
    env_key = logical_name.upper().replace(" ", "_") + "_TABLE"
    # Common patterns from CDK
    mapping = {
        "CatProfiles": os.environ.get("CAT_PROFILES_TABLE", "CatProfiles"),
        "Devices": os.environ.get("DEVICES_TABLE", "Devices"),
        "FeedingEvents": os.environ.get("FEEDING_EVENTS_TABLE", "FeedingEvents"),
        "HealthMetrics": os.environ.get("HEALTH_METRICS_TABLE", "HealthMetrics"),
        "DeviceTelemetry": os.environ.get("DEVICE_TELEMETRY_TABLE", "DeviceTelemetry"),
        "VetRecords": os.environ.get("VET_RECORDS_TABLE", "VetRecords"),
    }
    return mapping.get(logical_name, logical_name)


if __name__ == "__main__":
    main()
