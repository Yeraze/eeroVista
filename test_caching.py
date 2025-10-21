#!/usr/bin/env python3
"""Test adding simple in-memory caching for hourly bandwidth data."""

from datetime import datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo
import time

# Simple cache decorator that expires after 5 minutes
cache = {}
cache_expiry = {}

def cached_hourly_data(func):
    def wrapper(*args, **kwargs):
        # Create cache key based on date
        tz = ZoneInfo("America/New_York")
        now = datetime.now(tz)
        cache_key = now.date().isoformat()
        
        # Check if we have valid cached data
        if cache_key in cache and cache_key in cache_expiry:
            if cache_expiry[cache_key] > time.time():
                print(f"✓ Cache hit for {cache_key}")
                return cache[cache_key]
        
        # Call function and cache result
        print(f"✗ Cache miss for {cache_key}, computing...")
        result = func(*args, **kwargs)
        
        # Cache for 5 minutes
        cache[cache_key] = result
        cache_expiry[cache_key] = time.time() + 300
        
        # Clean up old cache entries (keep only today)
        for key in list(cache.keys()):
            if key != cache_key:
                del cache[key]
                del cache_expiry[key]
        
        return result
    
    return wrapper

# Simulation
@cached_hourly_data
def expensive_query():
    time.sleep(2)  # Simulate 2s query
    return {"data": "result"}

print("First call (should be slow):")
start = time.time()
expensive_query()
print(f"Time: {time.time() - start:.2f}s\n")

print("Second call (should be instant from cache):")
start = time.time()
expensive_query()
print(f"Time: {time.time() - start:.2f}s\n")

print("Potential speedup for repeat requests: ~2.3s -> ~0.001s")
print("Cache invalidation: Automatic every 5 minutes + on date change")
