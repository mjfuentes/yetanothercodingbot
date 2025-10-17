# Bot Monitoring Dashboard

A real-time web dashboard for monitoring Claude bot metrics, including API usage, task execution, tool usage, and system health.

## Features

### Metrics Tracked

1. **Claude API Usage**
   - Total cost and requests
   - Cost breakdown by model (Haiku vs Sonnet)
   - Token usage (input/output)
   - Recent activity (24h/7d/30d)

2. **Task Execution**
   - Total tasks and success rate
   - Status breakdown (pending, in_progress, completed, failed)
   - Recent task activity
   - Task timeline

3. **Tool Usage**
   - Total tool calls
   - Most used tools with statistics
   - Success rates per tool
   - Average execution times

4. **Hook Usage**
   - Registered hooks count
   - Hook activity monitoring

5. **System Health**
   - Active tasks count
   - Recent errors (24h)
   - Data file sizes
   - System status

### Real-time Features

- Auto-refresh every 30 seconds
- Interactive time range selection (24h, 7d, 30d)
- Beautiful activity timeline chart
- Responsive design

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run Monitoring Server

```bash
# From telegram_bot directory
python monitoring_server.py
```

Or configure via environment variables:

```bash
export MONITORING_HOST=0.0.0.0
export MONITORING_PORT=5000
export MONITORING_DEBUG=false
python monitoring_server.py
```

### 3. Access Dashboard

Open your browser and navigate to:
```
http://localhost:5000
```

## API Endpoints

The monitoring server provides REST API endpoints:

- `GET /api/metrics/overview?hours=24` - Complete metrics snapshot
- `GET /api/metrics/claude-api?hours=24` - Claude API usage metrics
- `GET /api/metrics/tasks` - Task execution statistics
- `GET /api/metrics/tools?hours=24` - Tool usage metrics
- `GET /api/metrics/hooks` - Hook usage summary
- `GET /api/metrics/system` - System health metrics
- `GET /api/metrics/timeseries?hours=24&interval=60` - Time-series data for charts
- `GET /api/health` - Health check endpoint

### Example API Usage

```bash
# Get complete overview
curl http://localhost:5000/api/metrics/overview?hours=24

# Get Claude API metrics for last 7 days
curl http://localhost:5000/api/metrics/claude-api?hours=168

# Get task statistics
curl http://localhost:5000/api/metrics/tasks
```

## Architecture

### Components

1. **MetricsAggregator** (`metrics_aggregator.py`)
   - Aggregates data from all tracking systems
   - Provides unified metrics interface
   - Generates time-series data

2. **MonitoringServer** (`monitoring_server.py`)
   - Flask-based web server
   - REST API endpoints
   - Serves dashboard UI

3. **Dashboard UI** (`templates/dashboard.html`)
   - Real-time metrics visualization
   - Interactive charts using Chart.js
   - Responsive design

### Data Sources

The monitoring system reads from existing tracking files:

- `data/usage.json` - Cost tracker data
- `data/tasks.json` - Task manager data
- `data/tool_usage.json` - Tool usage tracker data
- `data/agent_status.json` - Agent status records

## Configuration

### Environment Variables

- `MONITORING_HOST` - Server host (default: `0.0.0.0`)
- `MONITORING_PORT` - Server port (default: `5000`)
- `MONITORING_DEBUG` - Enable debug mode (default: `false`)

### Customization

Edit `monitoring_server.py` to:
- Add custom metrics endpoints
- Modify data aggregation logic
- Configure refresh intervals

Edit `templates/dashboard.html` to:
- Customize UI appearance
- Add new visualizations
- Modify chart configurations

## Production Deployment

### Using systemd (Linux)

Create `/etc/systemd/system/bot-monitoring.service`:

```ini
[Unit]
Description=Bot Monitoring Dashboard
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/agentlab/telegram_bot
Environment="MONITORING_HOST=0.0.0.0"
Environment="MONITORING_PORT=5000"
ExecStart=/usr/bin/python3 monitoring_server.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable bot-monitoring
sudo systemctl start bot-monitoring
```

### Using Docker

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY telegram_bot/ .
EXPOSE 5000

CMD ["python", "monitoring_server.py"]
```

Build and run:
```bash
docker build -t bot-monitoring .
docker run -p 5000:5000 -v $(pwd)/data:/app/data bot-monitoring
```

### Behind Nginx (Reverse Proxy)

```nginx
server {
    listen 80;
    server_name monitoring.yourdomain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## Security

### Recommendations

1. **Authentication**: Add basic auth or OAuth to protect dashboard
2. **HTTPS**: Use SSL/TLS in production
3. **Firewall**: Restrict access to trusted IPs
4. **CORS**: Configure CORS policy for API endpoints

### Adding Basic Auth

Install flask-httpauth:
```bash
pip install flask-httpauth
```

Add to `monitoring_server.py`:
```python
from flask_httpauth import HTTPBasicAuth

auth = HTTPBasicAuth()

users = {
    "admin": "password"  # Change this!
}

@auth.verify_password
def verify_password(username, password):
    if username in users and users[username] == password:
        return username

@app.route("/")
@auth.login_required
def index():
    return render_template("dashboard.html")
```

## Troubleshooting

### Server won't start

- Check if port 5000 is already in use: `lsof -i :5000`
- Verify all dependencies are installed: `pip list`
- Check logs for errors

### No data showing

- Ensure bot has generated tracking data (`data/*.json` files exist)
- Verify file permissions for `data/` directory
- Check API endpoints directly: `curl http://localhost:5000/api/health`

### Chart not rendering

- Check browser console for JavaScript errors
- Verify Chart.js CDN is accessible
- Clear browser cache

## Development

### Adding New Metrics

1. Add collection method to `MetricsAggregator`:
```python
def get_custom_metrics(self) -> dict[str, Any]:
    # Your metric collection logic
    return {"custom_metric": value}
```

2. Add API endpoint to `monitoring_server.py`:
```python
@app.route("/api/metrics/custom")
def custom_metrics():
    metrics = metrics_aggregator.get_custom_metrics()
    return jsonify(metrics)
```

3. Update dashboard to display new metrics

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov

# Run tests
pytest telegram_bot/
```

## License

Same as parent project.
