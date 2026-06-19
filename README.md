# MDA System

A lightweight maritime domain awareness simulator built with FastAPI.

## Overview

This project simulates vessel tracking and anomaly detection in a Gulf of Guinea-style sector. It uses a FastAPI web app and WebSocket stream to deliver live tactical telemetry to a browser-based dashboard.

## Features

- Simulated vessel movement and dead reckoning
- AIS correlation against radar-like position reports
- Detection of dark targets and suspicious loitering behavior
- Simple dashboard served from `templates/index.html`
- WebSocket feed at `/ws/mda`

## Requirements

- Python 3.11+ recommended
- `fastapi`
- `uvicorn`
- `websockets`
- `shapely` (required by `main.py` for EEZ geometry checks)

## Installation

```bash
cd /home/promise/mda-system
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install shapely
```

## Run

```bash
python main.py
```

Then open the dashboard at:

- `http://127.0.0.1:8000`

## Notes

- The app serves a dashboard from `templates/index.html` and streams updates using `/ws/mda`.
- If the WebSocket or dashboard doesn't connect, confirm the virtual environment is active and dependencies are installed.
