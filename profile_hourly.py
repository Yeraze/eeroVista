#!/usr/bin/env python3
"""Profile the hourly bandwidth endpoint to identify performance bottlenecks."""

import time
import requests

def profile_endpoint():
    """Profile the /api/health/network/bandwidth-hourly endpoint."""
    url = "http://localhost:8080/api/network/bandwidth-hourly"

    print("Profiling endpoint:", url)
    print("-" * 60)

    # Warm up
    print("Warming up...")
    requests.get(url)

    # Profile multiple requests
    times = []
    for i in range(5):
        start = time.time()
        response = requests.get(url)
        elapsed = time.time() - start
        times.append(elapsed)

        print(f"Request {i+1}: {elapsed:.3f}s")

        if response.status_code == 200:
            data = response.json()
            total_data_points = sum(h["data_points"] for h in data["hourly_breakdown"])
            print(f"  - Total data points processed: {total_data_points}")
        else:
            print(f"  - ERROR: {response.status_code}")

    print("-" * 60)
    print(f"Average: {sum(times) / len(times):.3f}s")
    print(f"Min: {min(times):.3f}s")
    print(f"Max: {max(times):.3f}s")

if __name__ == "__main__":
    profile_endpoint()
