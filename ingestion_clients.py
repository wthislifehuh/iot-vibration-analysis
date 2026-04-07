import numpy as np
import time
import os
import pandas as pd
from dotenv import load_dotenv

from influxdb_client import InfluxDBClient, WriteOptions
from questdb.ingress import Sender
import clickhouse_connect
from compressive_sensing import CompressiveSenser

load_dotenv()

# Bindings fallback map
INFLUX_HOST = os.getenv("INFLUX_HOST", "127.0.0.1")
QUEST_HOST = os.getenv("QUEST_HOST", "127.0.0.1")
CH_HOST = os.getenv("CH_HOST", "127.0.0.1")

class BaseTSDBClient:
    """ Polymorphic Base Class for Phase 3 Compression Dispatch """
    def _insert_raw(self, table, sensor_id, start_time_ns, data, fs, is_comp):
        raise NotImplementedError

    def insert(self, sensor_id: str, start_time_ns: int, payload: np.ndarray, cs_strategy: str = 'eager'):
        # Inject Phase 3 Senser globally for all implementations
        senser = CompressiveSenser(frame_size=256, ratio=4)
        
        if cs_strategy == 'eager':
            y_frames, orig_len = senser.compress(payload)
            x_recon = senser.reconstruct_eagerly(y_frames, orig_len)
            self._insert_raw('vibration_data', sensor_id, start_time_ns, x_recon, 25600, is_comp=0)
            
        elif cs_strategy == 'idle':
            y_frames, orig_len = senser.compress(payload)
            y_flat = y_frames.flatten()
            # Sink minimal compressed array straight down to DB
            self._insert_raw('vibration_data', sensor_id, start_time_ns, y_flat, 25600/4, is_comp=1)
            
            # Setup lambda callback to commit fully rebuilt structure transparently
            def idle_commit(recon_data):
                self._insert_raw('vibration_data_recon', sensor_id, start_time_ns, recon_data, 25600, is_comp=0)
            senser.reconstruct_on_idle(y_frames, orig_len, idle_commit)
            
        elif cs_strategy == 'query':
            y_frames, orig_len = senser.compress(payload)
            self._insert_raw('vibration_data', sensor_id, start_time_ns, y_frames.flatten(), 25600/4, is_comp=1)
            
        else: # Standard Raw behavior from Phase 2
            self._insert_raw('vibration_data', sensor_id, start_time_ns, payload, 25600, is_comp=0)


class ClickHouseClientAPI(BaseTSDBClient):
    def __init__(self):
        self.client = clickhouse_connect.get_client(
            host=CH_HOST, port=8123, 
            username=os.getenv('CLICKHOUSE_USER', 'admin'), 
            password=os.getenv('CLICKHOUSE_PASSWORD', 'SuperSecretPassword123!')
        )
        self.client.command('''
            CREATE TABLE IF NOT EXISTS vibration_data (
                sensor_id LowCardinality(String), reading Float32, timestamp DateTime64(9), is_compressed UInt8
            ) ENGINE = MergeTree() ORDER BY (sensor_id, timestamp)
        ''')
        # Setup specific decoupled table for idle reconstruct callbacks
        self.client.command('''
            CREATE TABLE IF NOT EXISTS vibration_data_recon (
                sensor_id LowCardinality(String), reading Float32, timestamp DateTime64(9)
            ) ENGINE = MergeTree() ORDER BY (sensor_id, timestamp)
        ''')

    def _insert_raw(self, table, sensor_id, start_time_ns, data, fs, is_comp):
        time_step = int(1e9 / fs)
        timestamps = np.arange(len(data), dtype=np.int64) * time_step + start_time_ns
        df = pd.DataFrame({'sensor_id': sensor_id, 'reading': data.astype(np.float32), 'timestamp': pd.to_datetime(timestamps)})
        if 'recon' not in table:
            df['is_compressed'] = is_comp
        for i in range(0, len(df), 1000000):
            self.client.insert_df(table, df.iloc[i:i+1000000])


class InfluxClientAPI(BaseTSDBClient):
    def __init__(self):
        self.client = InfluxDBClient(
            url=f"http://{INFLUX_HOST}:8086", token=os.getenv('INFLUXDB_ADMIN_TOKEN', 'token'),
            org=os.getenv('INFLUXDB_ORG', 'iot_engineering'), timeout=100000
        )
        self.write_api = self.client.write_api(write_options=WriteOptions(batch_size=200000, flush_interval=1000))
        self.bucket = os.getenv('INFLUXDB_BUCKET', 'vibration_data')
        self.org = os.getenv('INFLUXDB_ORG', 'iot_engineering')

    def _insert_raw(self, table, sensor_id, start_time_ns, data, fs, is_comp):
        time_step = int(1e9 / fs)
        timestamps = np.arange(len(data), dtype=np.int64) * time_step + start_time_ns
        for i in range(0, len(data), 5000000):
            chunk_p = data[i:i+5000000]
            chunk_t = timestamps[i:i+5000000]
            df = pd.DataFrame({'r': chunk_p, 't': chunk_t})
            # Pack is_compressed into the TSDB struct layout inherently 
            lp = f"{table},sensor_id={sensor_id},is_compressed={is_comp} reading=" + df['r'].astype(str) + " " + df['t'].astype(str)
            self.write_api.write(bucket=self.bucket, org=self.org, record=lp.tolist())

    def wait_flush(self):
        self.write_api.flush()

    def close(self):
        self.write_api.close()
        self.client.close()


class QuestClientAPI(BaseTSDBClient):
    def __init__(self):
        self.host = QUEST_HOST
        self.port = 9009
        
    def _insert_raw(self, table, sensor_id, start_time_ns, data, fs, is_comp):
        time_step = int(1e9 / fs)
        timestamps = np.arange(len(data), dtype=np.int64) * time_step + start_time_ns
        df = pd.DataFrame({'sensor_id': sensor_id, 'is_compressed': str(is_comp), 'reading': data, 'timestamp': pd.to_datetime(timestamps)})
        with Sender(self.host, self.port) as sender:
            for i in range(0, len(df), 500000):
                sender.dataframe(df.iloc[i:i+500000], table_name=table, symbols=['sensor_id', 'is_compressed'], at='timestamp')
                sender.flush()
