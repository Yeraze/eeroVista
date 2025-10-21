#!/usr/bin/env python3
"""Analyze the SQL query performance for hourly bandwidth endpoint."""

import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Connect to the database
conn = sqlite3.connect('/home/yeraze/Development/eerovista/data/eerovista.db')
cursor = conn.cursor()

# Calculate time range (same as the endpoint)
tz = ZoneInfo("America/New_York")
now_local = datetime.now(tz)
today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
today_start_utc = today_start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
today_end_local = today_start_local + timedelta(days=1)
today_end_utc = today_end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

# Get timezone offset
offset_seconds = today_start_local.utcoffset().total_seconds()
offset_hours = int(offset_seconds / 3600)

interval_seconds = 30
rate_to_mb = interval_seconds / 8.0

# The actual query
query = f"""
SELECT 
    CAST((CAST(strftime('%H', timestamp) AS INTEGER) + {offset_hours}) % 24 AS INTEGER) as hour,
    SUM(COALESCE(bandwidth_down_mbps, 0.0) * {rate_to_mb}) as download_mb,
    SUM(COALESCE(bandwidth_up_mbps, 0.0) * {rate_to_mb}) as upload_mb,
    COUNT(id) as count
FROM device_connections
WHERE timestamp >= ? AND timestamp < ?
GROUP BY hour
"""

# Explain query plan
print("QUERY PLAN:")
print("=" * 80)
cursor.execute(f"EXPLAIN QUERY PLAN {query}", (today_start_utc, today_end_utc))
for row in cursor.fetchall():
    print(row)

print("\n" + "=" * 80)
print("ROW COUNT:")
cursor.execute(
    "SELECT COUNT(*) FROM device_connections WHERE timestamp >= ? AND timestamp < ?",
    (today_start_utc, today_end_utc)
)
row_count = cursor.fetchone()[0]
print(f"Total rows in range: {row_count:,}")

print("\n" + "=" * 80)
print("INDEX INFO:")
cursor.execute("PRAGMA index_list(device_connections)")
indexes = cursor.fetchall()
for idx in indexes:
    print(f"Index: {idx[1]}")
    cursor.execute(f"PRAGMA index_info({idx[1]})")
    for col in cursor.fetchall():
        print(f"  - Column: {col[2]}")

print("\n" + "=" * 80)
print("TABLE INFO:")
cursor.execute("SELECT COUNT(*) FROM device_connections")
total_rows = cursor.fetchone()[0]
print(f"Total rows in table: {total_rows:,}")

conn.close()
