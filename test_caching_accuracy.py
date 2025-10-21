#!/usr/bin/env python3
"""Test caching accuracy and performance for hourly bandwidth endpoint."""

import time
import requests
import json

def test_cache_accuracy():
    """Test that cached results are identical to non-cached results."""
    url = "http://localhost:8080/api/network/bandwidth-hourly"
    
    print("=" * 80)
    print("CACHE ACCURACY & PERFORMANCE TEST")
    print("=" * 80)
    
    # First request - should be a cache miss
    print("\n1. First request (cache miss - slow):")
    start1 = time.time()
    response1 = requests.get(url)
    elapsed1 = time.time() - start1
    
    if response1.status_code != 200:
        print(f"ERROR: Request 1 failed with status {response1.status_code}")
        print(response1.text)
        return False
    
    data1 = response1.json()
    print(f"   Time: {elapsed1:.3f}s")
    print(f"   Total download: {data1['totals']['download_mb']} MB")
    print(f"   Total upload: {data1['totals']['upload_mb']} MB")
    print(f"   Hourly breakdown entries: {len(data1['hourly_breakdown'])}")
    
    # Second request - should be a cache hit
    print("\n2. Second request (cache hit - fast):")
    start2 = time.time()
    response2 = requests.get(url)
    elapsed2 = time.time() - start2
    
    if response2.status_code != 200:
        print(f"ERROR: Request 2 failed with status {response2.status_code}")
        print(response2.text)
        return False
    
    data2 = response2.json()
    print(f"   Time: {elapsed2:.3f}s")
    print(f"   Total download: {data2['totals']['download_mb']} MB")
    print(f"   Total upload: {data2['totals']['upload_mb']} MB")
    print(f"   Hourly breakdown entries: {len(data2['hourly_breakdown'])}")
    
    # Third request - also should be cache hit
    print("\n3. Third request (cache hit - fast):")
    start3 = time.time()
    response3 = requests.get(url)
    elapsed3 = time.time() - start3
    
    if response3.status_code != 200:
        print(f"ERROR: Request 3 failed with status {response3.status_code}")
        print(response3.text)
        return False
    
    data3 = response3.json()
    print(f"   Time: {elapsed3:.3f}s")
    
    # Compare results
    print("\n" + "=" * 80)
    print("ACCURACY VERIFICATION")
    print("=" * 80)
    
    # Convert to JSON strings for comparison
    json1 = json.dumps(data1, sort_keys=True)
    json2 = json.dumps(data2, sort_keys=True)
    json3 = json.dumps(data3, sort_keys=True)
    
    if json1 == json2 == json3:
        print("✓ ALL RESULTS IDENTICAL - Cache is working correctly!")
    else:
        print("✗ RESULTS DIFFER - Cache has accuracy issues!")
        print("\nDifferences found:")
        if json1 != json2:
            print("  - Request 1 and Request 2 differ")
        if json1 != json3:
            print("  - Request 1 and Request 3 differ")
        if json2 != json3:
            print("  - Request 2 and Request 3 differ")
        return False
    
    # Performance comparison
    print("\n" + "=" * 80)
    print("PERFORMANCE IMPROVEMENT")
    print("=" * 80)
    
    avg_cached = (elapsed2 + elapsed3) / 2
    speedup = elapsed1 / avg_cached
    
    print(f"Request 1 (uncached): {elapsed1:.3f}s")
    print(f"Request 2 (cached):   {elapsed2:.3f}s ({elapsed1/elapsed2:.1f}x faster)")
    print(f"Request 3 (cached):   {elapsed3:.3f}s ({elapsed1/elapsed3:.1f}x faster)")
    print(f"\nAverage cached time:  {avg_cached:.3f}s")
    print(f"Speedup factor:       {speedup:.1f}x")
    
    if elapsed2 < elapsed1 * 0.1 and elapsed3 < elapsed1 * 0.1:
        print("\n✓ CACHE PERFORMANCE VERIFIED - At least 10x faster!")
        return True
    elif elapsed2 < elapsed1 and elapsed3 < elapsed1:
        print(f"\n⚠ Cache is faster but less than expected (expected >10x, got {speedup:.1f}x)")
        return True
    else:
        print("\n✗ CACHE NOT WORKING - No performance improvement detected")
        return False

if __name__ == "__main__":
    success = test_cache_accuracy()
    exit(0 if success else 1)
