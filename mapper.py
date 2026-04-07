import psycopg2
import os

class SensorMapper:
    def __init__(self):
        self.host = os.getenv("PG_HOST", "127.0.0.1")
        self.user = os.getenv("PG_USER", "postgres")
        self.pwd = os.getenv("PG_PASSWORD", "secretpswd")
        # In-memory dictionary cache to prevent crushing Postgres with high-frequency reads
        self.cache = {}
        
    def get_logical_id(self, hardware_id: str) -> str:
        """ MiddleWare translating Physical Node IDs to stable Logical IDs for timeseries. """
        if hardware_id in self.cache:
            return self.cache[hardware_id]
        
        try:
            conn = psycopg2.connect(host=self.host, user=self.user, password=self.pwd, dbname="iot_metadata")
            cur = conn.cursor()
            cur.execute("SELECT logical_id FROM sensor_mappings WHERE hardware_id = %s", (hardware_id,))
            res = cur.fetchone()
            cur.close()
            conn.close()
            
            if res:
                self.cache[hardware_id] = res[0]
                return res[0]
        except Exception as e:
            # During cold boots or if the ORM table isn't up, fail gracefully
            pass 
            
        # Default behavior: If unmapped, assume logistical == hardware
        self.cache[hardware_id] = hardware_id
        return hardware_id
