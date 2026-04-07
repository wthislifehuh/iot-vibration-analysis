from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, DateTime, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import os
import csv
import clickhouse_connect
from datetime import datetime
import sys

# Allows loading the compressive_sensing module from parent workspace layer
sys.path.append(".")
try:
    from compressive_sensing import CompressiveSenser
except ImportError:
    CompressiveSenser = None

PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "secretpswd")
PG_HOST = os.getenv("PG_HOST", "127.0.0.1")

SQLALCHEMY_DATABASE_URL = f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}/iot_metadata"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class SensorMapping(Base):
    __tablename__ = "sensor_mappings"
    hardware_id = Column(String, primary_key=True, index=True)
    logical_id = Column(String, index=True)
    online = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="IoT Vibration Platform API", description="Phase 4 UI Data Integration logic")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RemapRequest(BaseModel):
    logical_id: str
    new_hardware_id: str

@app.get("/sensors")
def list_sensors(db: Session = Depends(get_db)):
    sensors = db.query(SensorMapping).all()
    logical_map = {}
    for s in sensors:
        if s.logical_id not in logical_map or s.updated_at > logical_map[s.logical_id]['updated_at']:
            logical_map[s.logical_id] = {
                "logical_id": s.logical_id, 
                "hardware_id": s.hardware_id, 
                "online": s.online, 
                "updated_at": s.updated_at
            }
    return list(logical_map.values())

@app.post("/sensors/remap")
def remap_sensor(req: RemapRequest, db: Session = Depends(get_db)):
    db_sensor = db.query(SensorMapping).filter(SensorMapping.hardware_id == req.new_hardware_id).first()
    if not db_sensor:
        db_sensor = SensorMapping(hardware_id=req.new_hardware_id, logical_id=req.logical_id, online=True)
        db.add(db_sensor)
    else:
        db_sensor.logical_id = req.logical_id
        db_sensor.updated_at = datetime.utcnow()
    db.commit()
    return {"status": "remapped", "logical_id": req.logical_id, "active_hardware_id": req.new_hardware_id}

def get_clickhouse_client():
    CH_HOST = os.getenv("CH_HOST", "127.0.0.1")
    return clickhouse_connect.get_client(
        host=CH_HOST, port=8123, 
        username=os.getenv('CLICKHOUSE_USER', 'admin'), 
        password=os.getenv('CLICKHOUSE_PASSWORD', 'SuperSecretPassword123!')
    )

@app.get("/sensors/{logical_id}/data")
def get_sensor_data(logical_id: str, start: str = None, end: str = None, strategy: str = "query"):
    try:
        client = get_clickhouse_client()
        query = f"SELECT timestamp, hardware_id, reading, is_compressed FROM vibration_data WHERE logical_id = '{logical_id}'"
        if start: query += f" AND timestamp >= parseDateTimeBestEffort('{start}')"
        if end:   query += f" AND timestamp <= parseDateTimeBestEffort('{end}')"
        query += " ORDER BY timestamp ASC LIMIT 10000"
        
        res = client.query(query)
        
        if strategy == 'query' and CompressiveSenser and len(res.result_rows) > 0 and res.result_rows[0][3] == 1:
            senser = CompressiveSenser(frame_size=256, ratio=4)
            compressed_vals = [r[2] for r in res.result_rows if r[3] == 1]
            
            if compressed_vals:
                import numpy as np
                y_arr = np.array(compressed_vals, dtype=np.float32)
                M = senser.M
                valid_len = (len(y_arr) // M) * M
                y_frames = y_arr[:valid_len].reshape(-1, M)
                
                x_recon = senser.reconstruct_on_query(y_frames, orig_len=len(y_frames)*256)
                return {
                    "logical_id": logical_id,
                    "strategy_employed": "QUERY (Dynamically Reconstructed via OMP L1)",
                    "data_length": len(x_recon),
                    "data_sample": list(x_recon[:150].astype(float)) 
                }

        return {
            "logical_id": logical_id,
            "strategy_employed": "EAGER/RAW (Pulled directly from storage)",
            "data": [{"timestamp": r[0].isoformat() if hasattr(r[0], 'isoformat') else str(r[0]), "hardware_id": r[1], "reading": r[2]} for r in res.result_rows[:150]]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/benchmark/results")
def get_benchmark_results():
    if not os.path.exists("results.csv"):
        raise HTTPException(status_code=404, detail="results.csv not found")
    with open("results.csv", mode='r', newline='') as f:
        reader = csv.DictReader(f)
        return list(reader)
