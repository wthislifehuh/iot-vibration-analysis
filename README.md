# IoT Vibration Analysis Platform

A complete, end-to-end Dockerized platform designed to ingest, benchmark, and serve 25.6 kHz machine vibration data arrays utilizing mathematical Compressive Sensing paradigms for massive storage reduction.

## System Architecture

Our cluster encompasses a centralized TSDB core benchmark suite isolating native array injections across **ClickHouse**, **QuestDB**, and **InfluxDB**, dynamically bridged through a Mosquitto MQTT pipe. It incorporates a PostgreSQL mapping cache to ensure Logical continuity regardless of physical edge hardware swaps and surfaces operations through a FastAPI & React Vite Glassmorphic dashboard.

---

## ⚡ One-Command Startup Guide

If this is a completely fresh environment, initialize the isolated host persistence volumes:
```bash
docker volume create influxdb_data
docker volume create influxdb_config
docker volume create questdb_data
docker volume create clickhouse_data
docker volume create clickhouse_log
docker volume create mosquitto_data
docker volume create mosquitto_log
docker volume create postgres_data
```

To build and launch the **entire consolidated pipeline** (databases, MQTT, Python microservices, FastAPI backend, and Nginx React Frontend), simply execute:

```bash
docker compose up -d --build
```

### Accessing the Ecosystem
Once the cluster reaches quorum, you can access the interface safely bound to localhost loopbacks:
- **UI Dashboard:** http://127.0.0.1
- **ClickHouse Play UI:** http://127.0.0.1:8123
- **QuestDB Admin:** http://127.0.0.1:9000
- **InfluxDB 2 Console:** http://127.0.0.1:8086
