#!/usr/bin/env python3
"""
Simple NFT collection scanner
Checks floor price and supply from OpenSea API
"""
import requests
import sys
from datetime import datetime

def get_collection_stats(slug):
    """Get collection stats from OpenSea"""
    url = f"https://api.opensea.io/api/v1/collection/{slug}"
    
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            stats = data.get('collection', {}).get('stats', {})
            
            print(f"\n📊 Collection: {slug}")
            print(f"Floor Price: {stats.get('floor_price', 0)} ETH")
            print(f"Total Supply: {stats.get('total_supply', 0)}")
            print(f"Owners: {stats.get('num_owners', 0)}")
            print(f"Volume (24h): {stats.get('one_day_volume', 0)} ETH")
            return True
        else:
            print(f"❌ Error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        collection = sys.argv[1]
    else:
        collection = "boredapeyachtclub"  # Default example
    
    print(f"🔍 NFT Collection Scanner")
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    get_collection_stats(collection)
