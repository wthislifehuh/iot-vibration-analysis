import concurrent.futures
import time
import numpy as np
import subprocess
import csv
import argparse
from ingestion_clients import InfluxClientAPI, QuestClientAPI, ClickHouseClientAPI

def generate_noise(samples):
    """Generate realistic uncompressed vibration array."""
    return np.random.uniform(-10.0, 10.0, samples).astype(np.float32)


def worker_influx(sensor_id, samples, start_ns, strategy):
    payload = generate_noise(samples)
    client = InfluxClientAPI()
    t0 = time.time()
    try:
        client.insert(sensor_id, start_ns, payload, cs_strategy=strategy)
        client.wait_flush()
        client.close()
    except Exception as e:
        return sensor_id, False, time.time() - t0, str(e)
    return sensor_id, True, time.time() - t0, ""


def worker_quest(sensor_id, samples, start_ns, strategy):
    payload = generate_noise(samples)
    client = QuestClientAPI()
    t0 = time.time()
    try:
        client.insert(sensor_id, start_ns, payload, cs_strategy=strategy)
    except Exception as e:
        return sensor_id, False, time.time() - t0, str(e)
    return sensor_id, True, time.time() - t0, ""


def worker_clickhouse(sensor_id, samples, start_ns, strategy):
    payload = generate_noise(samples)
    client = ClickHouseClientAPI()
    t0 = time.time()
    try:
        client.insert(sensor_id, start_ns, payload, cs_strategy=strategy)
    except Exception as e:
        return sensor_id, False, time.time() - t0, str(e)
    return sensor_id, True, time.time() - t0, ""


def measure_volumes():
    cmd = [
        "docker", "run", "--rm",
        "-v", "influxdb_data:/vols/influxdb",
        "-v", "questdb_data:/vols/questdb",
        "-v", "clickhouse_data:/vols/clickhouse",
        "alpine", "sh", "-c",
        "du -sm /vols/*"
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        sizes = {}
        for line in res.stdout.strip().split('\n'):
            parts = line.split()
            if len(parts) == 2:
                sizes[parts[1].split('/')[-1]] = int(parts[0])
        return sizes
    except Exception as e:
        print("Volume measure warning:", e)
        return {"influxdb": 0, "questdb": 0, "clickhouse": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sensors', type=int, default=10)
    parser.add_argument('--mb-per-sensor', type=int, default=50) # Reduced default scale for testing speed. Pass 100 for true payload.
    parser.add_argument('--cs-strategy', type=str, choices=['raw', 'eager', 'idle', 'query'], default='raw')
    args = parser.parse_args()
    
    # 1 float32 takes 4 bytes, so (MB * 1024 * 1024) / 4 gives the sample count
    samples_per_sensor = int((args.mb_per_sensor * 1024 * 1024) / 4)
    print(f"Starting Benchmark: {args.sensors} sensors, {args.mb_per_sensor} MB each ({samples_per_sensor} sample rows/sensor)")
    
    start_ns = time.time_ns()
    results = []

    # Get initial Docker host overhead mapping sizes
    init_vols = measure_volumes()

    engines = [
        ("clickhouse", worker_clickhouse),
        ("questdb", worker_quest),
        ("influxdb", worker_influx)
    ]
    
    # Process sequentially, guaranteeing isolation & fair CPU metrics.
    # The inner loop will fork 10 simultaneous processes loading the specific databases
    for target_db, worker_fn in engines:
        print(f"\n--- Load Testing {target_db.upper()} ---")
        init_vol = measure_volumes().get(target_db, 0)
        
        start_time = time.time()
        successes = 0
        total_time = 0
        
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.sensors) as executor:
            futures = []
            for i in range(args.sensors):
                # sensor id mappings 
                sensor_id = f"sensor_{target_db}_{i}"
                futures.append(executor.submit(worker_fn, sensor_id, samples_per_sensor, start_ns, args.cs_strategy))
            
            for future in concurrent.futures.as_completed(futures):
                s_id, ok, elapsed, err = future.result()
                if ok:
                    successes += 1
                else:
                    print(f"[{s_id}] Failed during insert loop: {err}")
        
        wall_clock = time.time() - start_time
        print("Cooling down 2 seconds for IO blocks to flush to WAL/SSD...")
        time.sleep(2) 
        
        final_vol = measure_volumes().get(target_db, 0)
        delta_mb = final_vol - init_vol
        rows = successes * samples_per_sensor
        
        # Mathematical computations
        raw_mb = args.sensors * args.mb_per_sensor
        overhead = delta_mb / raw_mb if raw_mb > 0 else 0
        rate = rows / wall_clock if wall_clock > 0 else 0

        print(f"DB: {target_db}")
        print(f"Total Rows Injected: {rows}")
        print(f"Wall Clock Time: {wall_clock:.2f} s")
        print(f"Sustained Row Ingestion Rate: {rate:,.0f} rows/s")
        print(f"Raw Storage Metric Increase: {delta_mb} MB")
        print(f"Effective Database Overhead Ratio: {overhead:.2f}x")
        
        results.append({
            "database": target_db,
            "sensors": args.sensors,
            "raw_data_mb": raw_mb,
            "ingestion_time_s": round(wall_clock, 2),
            "volume_size_mb": delta_mb,
            "overhead_ratio": round(overhead, 2),
            "rows_per_sec": round(rate, 2)
        })

    with open("results.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    print("\nBenchmark tests complete! Results preserved locally to results.csv")

if __name__ == "__main__":
    main()
