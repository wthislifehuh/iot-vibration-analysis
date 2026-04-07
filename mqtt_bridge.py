import paho.mqtt.client as mqtt
import json
import numpy as np
import time
import os
import threading
from ingestion_clients import InfluxClientAPI, QuestClientAPI, ClickHouseClientAPI

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")

# Build target class objects
influx = InfluxClientAPI()
quest = QuestClientAPI()
ch = ClickHouseClientAPI()

print(f"System boot MQTT Ingestion bridge at {MQTT_HOST}:1883")

def on_connect(client, userdata, flags, rc):
    print("Linked to local mosquitto bus, result parameter =>", rc)
    client.subscribe("sensors/+/vibration")

def on_message(client, userdata, msg):
    try:
        topic_parts = msg.topic.split('/')
        sensor_id = topic_parts[1]
        
        data = json.loads(msg.payload.decode('utf-8'))
        start_ns = data['start_time_ns']
        payload = np.array(data['data'], dtype=np.float32)
        
        # Decouple DB HTTP requests into fire-and-forget worker sweeps so Mosquitto Paho IO loop is never blocked
        if os.getenv("DO_INGESTION", "true").lower() == "true":
            threading.Thread(target=influx.insert, args=(sensor_id, start_ns, payload)).start()
            threading.Thread(target=quest.insert, args=(sensor_id, start_ns, payload)).start()
            threading.Thread(target=ch.insert, args=(sensor_id, start_ns, payload)).start()
        
        print(f"Successfully bridged data bundle from: {sensor_id}: {len(payload)} samples")
    except Exception as e:
        print("Exception during Mosquitto ingestion route processing:", e)

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_HOST, 1883, 60)
client.loop_forever()
