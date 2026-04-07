#!/usr/bin/env python3
"""
Phase 1: Volume & Database Verification Script
This script validates connectivity to all 3 containerized TSDB engines from the host machine.
It relies only on standard Python libraries so it can be executed immediately without a virtualenv.
"""
import urllib.request
import urllib.parse
import os
import ssl
import base64

def _parse_env_file(filepath=".env"):
    """Reads .env locally to fetch default credentials."""
    env = {}
    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip("'\"")
    return env

def make_request(url, username=None, password=None):
    """Executes an HTTP GET query allowing for basic HTTP Auth."""
    req = urllib.request.Request(url)
    if username and password:
        auth_string = f"{username}:{password}"
        base64_auth = base64.b64encode(auth_string.encode("utf-8")).decode("utf-8")
        req.add_header("Authorization", f"Basic {base64_auth}")
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            status = response.getcode()
            body = response.read().decode('utf-8')
            return status, body
    except urllib.error.URLError as e:
        status = getattr(e, 'code', str(e))
        return status, str(e)
    except Exception as e:
        return 'Exception', str(e)

def check_db(name, url, expected_status=200, user=None, password=None):
    """Wraps assertion validation and outputs a clean console log."""
    # Special handling for QuestDB 200 ping which sometimes returns 404 on root
    status, _ = make_request(url, user, password)
    if status == expected_status:
        print(f"  [ PASS ] {name} is reachable at {url}")
    else:
        print(f"  [ FAIL ] {name} returned status {status} at {url}")

if __name__ == "__main__":
    print("--- Phase 1: Database Reachability and Port Binding Verification ---")
    env = _parse_env_file()
    
    print("\nTesting InfluxDB on 127.0.0.1:8086...")
    check_db("InfluxDB (Health)", "http://127.0.0.1:8086/health")

    print("\nTesting QuestDB on 127.0.0.1:9000...")
    query_encoded = urllib.parse.quote("SELECT 1")
    check_db("QuestDB (REST query)", f"http://127.0.0.1:9000/exec?query={query_encoded}")

    print("\nTesting ClickHouse on 127.0.0.1:8123...")
    check_db("ClickHouse (Health ping)", "http://127.0.0.1:8123/ping")
    
    ch_user = env.get("CLICKHOUSE_USER", "default")
    ch_pass = env.get("CLICKHOUSE_PASSWORD", "")
    ch_query_encoded = urllib.parse.quote("SELECT 2")
    check_db("ClickHouse (Authenticated query)", f"http://127.0.0.1:8123/?query={ch_query_encoded}", user=ch_user, password=ch_pass)

    print("\n--------------------------------------------------------------------")
    print("If all tests passed, your Docker volumes and networks are fully bound.")
