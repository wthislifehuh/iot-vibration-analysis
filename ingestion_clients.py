import numpy as np
import time
import os
import pandas as pd
from dotenv import load_dotenv

from influxdb_client import InfluxDBClient, WriteOptions
from questdb.ingress import Sender
import clickhouse_connect

load_dotenv()

# Map hosts based on where we are running (docker vs host)
INFLUX_HOST = os.getenv("INFLUX_HOST", "127.0.0.1")
QUEST_HOST = os.getenv("QUEST_HOST", "127.0.0.1")
CH_HOST = os.getenv("CH_HOST", "127.0.0.1")
INFLUX_URL = f"http://{INFLUX_HOST}:8086"

class InfluxClientAPI:
    def __init__(self):
        self.client = InfluxDBClient(
            url=INFLUX_URL,
            token=os.getenv('INFLUXDB_ADMIN_TOKEN', 'Th1s-Is-A-S3cr3t-T0k3n-F0r-V1br4t10n-An4lys1s'),
            org=os.getenv('INFLUXDB_ORG', 'iot_engineering'),
            timeout=300000
        )
        self.write_api = self.client.write_api(write_options=WriteOptions(batch_size=500000, flush_interval=1000))
        self.bucket = os.getenv('INFLUXDB_BUCKET', 'vibration_data')
        self.org = os.getenv('INFLUXDB_ORG', 'iot_engineering')

    def insert(self, sensor_id: str, start_time_ns: int, payload: np.ndarray):
        # Calculate timestamps mapping up from the start_ns parameter (fs = 25.6 kHz)
        time_step = int(1e9 / 25600)
        timestamps = np.arange(len(payload), dtype=np.int64) * time_step + start_time_ns
        
        # Using string vectorization in pandas for maximum LP generation throughput
        batch_size = 5000000
        for i in range(0, len(payload), batch_size):
            chunk_p = payload[i:i+batch_size]
            chunk_t = timestamps[i:i+batch_size]
            df = pd.DataFrame({'r': chunk_p, 't': chunk_t})
            lp = f"vibration_data,sensor_id={sensor_id} reading=" + df['r'].astype(str) + " " + df['t'].astype(str)
            self.write_api.write(bucket=self.bucket, org=self.org, record=lp.tolist())
    
    def wait_flush(self):
        self.write_api.flush()

    def close(self):
        self.write_api.close()
        self.client.close()


class QuestClientAPI:
    def __init__(self):
        self.host = QUEST_HOST
        self.port = 9009
        
    def insert(self, sensor_id: str, start_time_ns: int, payload: np.ndarray):
        time_step = int(1e9 / 25600)
        timestamps = np.arange(len(payload), dtype=np.int64) * time_step + start_time_ns
        
        df = pd.DataFrame({
            'sensor_id': sensor_id,
            'reading': payload,
            'timestamp': pd.to_datetime(timestamps)
        })
        
        batch_size = 1000000
        # High speed TCP line protocol via Sender class
        with Sender(self.host, self.port) as sender:
            for i in range(0, len(df), batch_size):
                chunk = df.iloc[i:i+batch_size]
                sender.dataframe(
                    chunk,
                    table_name='vibration_data',
                    symbols=['sensor_id'],
                    at='timestamp'
                )
                sender.flush()


class ClickHouseClientAPI:
    def __init__(self):
        # Make sure our connection params map to the host's 8123 proxy
        self.client = clickhouse_connect.get_client(
            host=CH_HOST, 
            port=8123, 
            username=os.getenv('CLICKHOUSE_USER', 'admin'), 
            password=os.getenv('CLICKHOUSE_PASSWORD', 'SuperSecretPassword123!')
        )
        # Ensure target schema exists
        self.client.command('''
            CREATE TABLE IF NOT EXISTS vibration_data (
                sensor_id LowCardinality(String),
                reading Float32,
                timestamp DateTime64(9)
            ) ENGINE = MergeTree()
            ORDER BY (sensor_id, timestamp)
        ''')

    def insert(self, sensor_id: str, start_time_ns: int, payload: np.ndarray):
        time_step = int(1e9 / 25600)
        timestamps = np.arange(len(payload), dtype=np.int64) * time_step + start_time_ns
        
        df = pd.DataFrame({
            'sensor_id': sensor_id,
            'reading': payload.astype(np.float32),
            'timestamp': pd.to_datetime(timestamps)
        })
        
        # Chunk logic for ClickHouse binary HTTP inserts
        batch_size = 2000000
        for i in range(0, len(df), batch_size):
            chunk = df.iloc[i:i+batch_size]
            self.client.insert_df('vibration_data', chunk)
