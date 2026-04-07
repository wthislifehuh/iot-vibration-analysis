import numpy as np
import time
import os
import pandas as pd
from dotenv import load_dotenv

from influxdb_client import InfluxDBClient, WriteOptions
from questdb.ingress import Sender
import clickhouse_connect
from compressive_sensing import CompressiveSenser
from mapper import SensorMapper

load_dotenv()

INFLUX_HOST = os.getenv("INFLUX_HOST", "127.0.0.1")
QUEST_HOST = os.getenv("QUEST_HOST", "127.0.0.1")
CH_HOST = os.getenv("CH_HOST", "127.0.0.1")

mapper = SensorMapper()

class BaseTSDBClient:
    """ Architectural bridge for applying phase 4 logic natively across TSDB instances. """
    def _insert_raw(self, table, logical_id, hardware_id, start_time_ns, data, fs, is_comp):
        raise NotImplementedError

    def insert(self, hardware_id: str, start_time_ns: int, payload: np.ndarray, cs_strategy: str = 'eager'):
        # PHASE 4 ID Continuity Logic applied at transit boundary
        logical_id = mapper.get_logical_id(hardware_id)
        senser = CompressiveSenser(frame_size=256, ratio=4)
        
        if cs_strategy == 'eager':
            y_frames, orig_len = senser.compress(payload)
            x_recon = senser.reconstruct_eagerly(y_frames, orig_len)
            self._insert_raw('vibration_data', logical_id, hardware_id, start_time_ns, x_recon, 25600, is_comp=0)
            
        elif cs_strategy == 'idle':
            y_frames, orig_len = senser.compress(payload)
            y_flat = y_frames.flatten()
            self._insert_raw('vibration_data', logical_id, hardware_id, start_time_ns, y_flat, 25600/4, is_comp=1)
            
            # Simulated callback writes 
            def idle_commit(recon_data):
                self._insert_raw('vibration_data_recon', logical_id, hardware_id, start_time_ns, recon_data, 25600, is_comp=0)
            senser.reconstruct_on_idle(y_frames, orig_len, idle_commit)
            
        elif cs_strategy == 'query':
            y_frames, orig_len = senser.compress(payload)
            self._insert_raw('vibration_data', logical_id, hardware_id, start_time_ns, y_frames.flatten(), 25600/4, is_comp=1)
            
        else: # Standard unstructured injection
            self._insert_raw('vibration_data', logical_id, hardware_id, start_time_ns, payload, 25600, is_comp=0)


class ClickHouseClientAPI(BaseTSDBClient):
    def __init__(self):
        self.client = clickhouse_connect.get_client(
            host=CH_HOST, port=8123, 
            username=os.getenv('CLICKHOUSE_USER', 'admin'), 
            password=os.getenv('CLICKHOUSE_PASSWORD', 'SuperSecretPassword123!')
        )
        self.client.command('''
            CREATE TABLE IF NOT EXISTS vibration_data (
                logical_id LowCardinality(String), hardware_id LowCardinality(String), reading Float32, timestamp DateTime64(9), is_compressed UInt8
            ) ENGINE = MergeTree() ORDER BY (logical_id, timestamp)
        ''')

    def _insert_raw(self, table, logical_id, hardware_id, start_time_ns, data, fs, is_comp):
        time_step = int(1e9 / fs)
        timestamps = np.arange(len(data), dtype=np.int64) * time_step + start_time_ns
        df = pd.DataFrame({'logical_id': logical_id, 'hardware_id': hardware_id, 'reading': data.astype(np.float32), 'timestamp': pd.to_datetime(timestamps)})
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

    def _insert_raw(self, table, logical_id, hardware_id, start_time_ns, data, fs, is_comp):
        time_step = int(1e9 / fs)
        timestamps = np.arange(len(data), dtype=np.int64) * time_step + start_time_ns
        for i in range(0, len(data), 5000000):
            chunk_p = data[i:i+5000000]
            chunk_t = timestamps[i:i+5000000]
            df = pd.DataFrame({'r': chunk_p, 't': chunk_t})
            lp = f"{table},logical_id={logical_id},hardware_id={hardware_id},is_compressed={is_comp} reading=" + df['r'].astype(str) + " " + df['t'].astype(str)
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
        
    def _insert_raw(self, table, logical_id, hardware_id, start_time_ns, data, fs, is_comp):
        time_step = int(1e9 / fs)
        timestamps = np.arange(len(data), dtype=np.int64) * time_step + start_time_ns
        df = pd.DataFrame({'logical_id': logical_id, 'hardware_id': hardware_id, 'is_compressed': str(is_comp), 'reading': data, 'timestamp': pd.to_datetime(timestamps)})
        with Sender(self.host, self.port) as sender:
            for i in range(0, len(df), 500000):
                sender.dataframe(df.iloc[i:i+500000], table_name=table, symbols=['logical_id', 'hardware_id', 'is_compressed'], at='timestamp')
                sender.flush()
