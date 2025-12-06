# Hybrid Local/AWS Development Environment

This document describes the hybrid development environment that automatically switches between local and AWS backends based on availability.

## Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend      │    │   Backend       │    │   Database      │
│   (Next.js)     │◄──►│   (FastAPI)     │◄──►│   (PostgreSQL)  │
│   Port 3000     │    │   Port 8000     │    │   Port 5432     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   AWS Frontend  │    │   AWS Backend   │    │   AWS Database  │
│   54.254.150.31│    │   54.254.150.31 │    │   (Container)   │
│   Port 3000     │    │   Port 8000     │    │   Port 5432     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Environment Detection

### Frontend (Next.js)
- **Automatic Detection**: Based on `window.location.hostname`
- **Local**: `localhost`, `127.0.0.1`
- **AWS**: Contains `54.254.150.31` or `ec2`
- **Health Monitoring**: Checks local backend every 5 seconds
- **Failover**: Automatically switches to AWS when local backend is unhealthy

### Backend (FastAPI)
- **Environment Variables**: `ENVIRONMENT=local|aws`
- **CORS Configuration**: Dynamic based on environment
- **Health Endpoints**: `/health` and `/api/health`

## Configuration Files

### Environment Files
- `.env.local` - Local development settings
- `.env.aws` - AWS production settings
- `.env` - Base configuration

### Docker Compose Profiles
- `--profile local` - Local development (default)
- `--profile aws` - AWS production

## Usage

### Starting Local Development
```bash
# Start local environment
./start_local.sh

# Or manually
docker compose --profile local up -d
```

### Starting AWS Environment
```bash
# Start AWS environment
./start_aws.sh

# Or manually
docker compose --profile aws up -d
```

### Syncing to AWS
```bash
# Deploy to AWS
./sync_to_aws.sh
```

### Testing Failover
```bash
# Run comprehensive tests
./test_failover.sh
```

## API Endpoints

### Health Checks
- `GET /health` - Basic health check
- `GET /api/health` - Detailed health with environment info

### Environment Information
```json
{
  "status": "healthy",
  "environment": "local",
  "is_local": true,
  "is_aws": false,
  "cors_origins": ["http://localhost:3000", "http://127.0.0.1:3000"]
}
```

## Frontend Features

### Environment Status Indicators
- **🏠 Local** - Running in local environment
- **☁️ AWS** - Running in AWS environment
- **✅ Local Backend** - Using local backend
- **❌ Using AWS Backend** - Failover to AWS backend

### Automatic Failover
1. **Health Monitoring**: Checks local backend every 5 seconds
2. **Failover Trigger**: When local backend becomes unhealthy
3. **Recovery**: Automatically switches back when local backend recovers
4. **Visual Feedback**: Status indicators update in real-time

## Development Workflow

### Local Development
1. **Start Local Environment**:
   ```bash
   ./start_local.sh
   ```

2. **Access Dashboard**:
   - Frontend: http://localhost:3000
   - Backend: http://localhost:8000
   - Database: localhost:5432

3. **Make Changes**: All changes are reflected immediately

### Deploying to AWS
1. **Sync Changes**:
   ```bash
   ./sync_to_aws.sh
   ```

2. **Access AWS Environment**:
   - Frontend: http://54.254.150.31:3000
   - Backend: http://54.254.150.31:8000

### Remote Access
When not on your Mac:
- **Automatic Detection**: Frontend detects it's not on localhost
- **AWS Routing**: All API calls go to AWS backend
- **Seamless Experience**: No configuration changes needed

## Troubleshooting

### Local Backend Not Starting
```bash
# Check logs
docker compose logs backend

# Restart backend
docker compose restart backend

# Check health
curl http://localhost:8000/health
```

### AWS Backend Not Accessible
```bash
# Check AWS connectivity
ping 54.254.150.31

# Test AWS backend
curl http://54.254.150.31:8000/health

# Deploy to AWS
./sync_to_aws.sh
```

### Frontend Not Detecting Environment
1. **Check Browser Console**: Look for environment detection logs
2. **Verify API Calls**: Check Network tab for API requests
3. **Hard Refresh**: Ctrl+F5 or Cmd+Shift+R

### Failover Not Working
1. **Check Health Monitoring**: Look for health check logs in console
2. **Verify AWS Backend**: Ensure AWS backend is accessible
3. **Check Network**: Verify no firewall blocking AWS access

## Environment Variables

### Local Development
```bash
ENVIRONMENT=local
NODE_ENV=development
API_BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000/api
```

### AWS Production
```bash
ENVIRONMENT=aws
NODE_ENV=production
API_BASE_URL=http://54.254.150.31:8000
FRONTEND_URL=http://54.254.150.31:3000
NEXT_PUBLIC_API_URL=http://54.254.150.31:8000/api
```

## Security Considerations

### CORS Configuration
- **Local**: Allows localhost and 127.0.0.1
- **AWS**: Allows AWS instance IP
- **Dynamic**: Automatically configured based on environment

### API Keys
- **Shared**: Same API key for both environments
- **Secure**: Keys stored in environment files
- **Consistent**: Same authentication across environments

## Monitoring

### Health Checks
- **Backend**: `/health` endpoint with environment info
- **Frontend**: Automatic health monitoring with visual indicators
- **Database**: PostgreSQL health checks in Docker

### Logs
- **Backend**: `docker compose logs backend`
- **Frontend**: `docker compose logs frontend`
- **Database**: `docker compose logs db`

## Performance

### Local Development
- **Fast**: All services run locally
- **Real-time**: Changes reflected immediately
- **Offline**: Works without internet connection

### AWS Production
- **Reliable**: Always available from anywhere
- **Scalable**: Can handle multiple users
- **Backup**: Automatic failover for local development

## Best Practices

1. **Always use local for development**
2. **Deploy to AWS for production/testing**
3. **Test failover regularly**
4. **Monitor environment status indicators**
5. **Keep AWS environment in sync**
6. **Use version control for all changes**

## Support

For issues or questions:
1. **Check logs**: `docker compose logs [service]`
2. **Run tests**: `./test_failover.sh`
3. **Verify environment**: Check status indicators in UI
4. **Restart services**: `docker compose restart [service]`

