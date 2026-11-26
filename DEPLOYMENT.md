# Deployment Information

## Public URL
https://agent-production-b4d250eb.up.railway.app

## Platform
Railway (Project: `day14-production-agent`, Environment: `production`, Region: `iad`)

- **Agent service:** `agent` (built from `06-lab-complete/Dockerfile` via `railway.toml`)
- **Redis service:** `Redis` (`redis:8.2` with persistent volume `/data`, connected over Railway private network)

## Test Commands

### Health Check
```bash
curl https://agent-production-b4d250eb.up.railway.app/health
# Expected: {"status":"ok"}
```

### Readiness Check (Redis Connection)
```bash
curl https://agent-production-b4d250eb.up.railway.app/ready
# Expected: {"status":"ready","redis":"connected"}
```

### Authentication Check (Unauthenticated -> 401)
```bash
curl -i -X POST https://agent-production-b4d250eb.up.railway.app/ask \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected: HTTP 401 Unauthorized
```

### API Test (with authentication -> 200)
```bash
curl -X POST https://agent-production-b4d250eb.up.railway.app/ask \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
```

## Environment Variables Set
- `PORT` (injected automatically by Railway)
- `REDIS_URL` (`${{Redis.REDIS_URL}}` internal service reference)
- `AGENT_API_KEY` (stored securely in Railway service variables)
- `ENVIRONMENT` (`production`)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`10`)
- `MONTHLY_BUDGET_USD` (`10`)
- `LOG_LEVEL` (`INFO`)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
