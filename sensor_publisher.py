import paho.mqtt.client as mqtt
import json
import time
import os
import random

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
client = mqtt.Client()
client.connect(MQTT_HOST, 1883, 60)

sensor_id = "sensor_mqtt_" + str(random.randint(100, 999))
print(f"Activated virtual transmitter agent for [{sensor_id}] pushing into => {MQTT_HOST}")

while True:
    try:
        # Simulate an interval push sequence corresponding to 25.6 kHz downscale batch 
        # (about 0.1 seconds of structural frequency data)
        samples = 2560
        payload = [random.uniform(-5.0, 5.0) for _ in range(samples)]
        
        msg = {
            "sensor_id": sensor_id,
            "start_time_ns": time.time_ns(),
            "data": payload
        }
        
        topic = f"sensors/{sensor_id}/vibration"
        client.publish(topic, json.dumps(msg), qos=0)
        print(f"Broadcast envelope: {samples} measurements mapped toward => {topic}")
        
        # 1.0 second pause throttle to prevent exploding RAM buffers with JSON allocations
        time.sleep(1)
    except Exception as e:
        print("Publisher critical runtime exception:", e)
        time.sleep(1)
