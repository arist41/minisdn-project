#!/usr/bin/env python3
"""
MINISDN Cluster Test Script
"""
import requests
import time
from datetime import datetime

nodes = {
    'node1': 'http://localhost:5001',
    'node2': 'http://localhost:5002', 
    'node3': 'http://localhost:5003'
}

print("🚀 MINISDN Cluster Monitor")
print("=" * 60)

def print_node_status(name, url):
    """Print status of a single node"""
    try:
        resp = requests.get(f"{url}/status", timeout=1)
        data = resp.json()
        
        if data['role'] == 'leader':
            icon = "👑"
            color = "\033[92m"  # Green
        elif data['role'] == 'candidate':
            icon = "🎯"
            color = "\033[93m"  # Yellow
        else:
            icon = "👤"
            color = "\033[94m"  # Blue
            
        reset = "\033[0m"
        
        print(f"{color}{icon} {name:5} | {data['role']:10} | Term: {data['term']:3} | "
              f"Leader: {data['leader'] or 'None':5} | Voted: {data['voted_for'] or 'None':5} | "
              f"Switches: {len(data['switches'])}{reset}")
        
        if data['switches']:
            for switch in data['switches']:
                master = data['switch_details'].get(str(switch), {}).get('master', 'Unknown')
                print(f"        ↳ s{switch}: master={master}")
        
        return data['role']
    except Exception as e:
        print(f"❌ {name}: OFFLINE - {e}")
        return None

while True:
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{timestamp}] Cluster Status:")
    
    leaders = []
    for name, url in nodes.items():
        role = print_node_status(name, url)
        if role == 'leader':
            leaders.append(name)
    
    # Check for multiple leaders (split brain)
    if len(leaders) > 1:
        print(f"\n⚠️  \033[91mWARNING: MULTIPLE LEADERS DETECTED! {leaders}\033[0m")
    elif len(leaders) == 1:
        print(f"\n✅ \033[92mSingle leader: {leaders[0]}\033[0m")
    else:
        print(f"\n⚠️  \033[93mNo leader elected\033[0m")
    
    print("-" * 60)
    print("Commands: curl -X POST http://localhost:500X/force_election")
    print("Press Ctrl+C to exit")
    
    time.sleep(2)
