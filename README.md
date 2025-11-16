# Automated Trading Platform

A full-stack automated trading platform built with FastAPI (backend) and Next.js (frontend).

## Project Structure

```
automated-trading-platform/
├── backend/
│   └── app/
│       ├── api/          # API routes
│       ├── core/         # Core configuration
│       ├── models/       # Database models
│       ├── schemas/      # Pydantic schemas
│       ├── services/     # Business logic
│       ├── utils/        # Utility functions
│       ├── deps/         # Dependencies
│       └── tests/        # Test files
├── frontend/             # Next.js application
├── docker-compose.yml    # Docker services
└── .env.example         # Environment variables template
```

## Services

- **Database**: PostgreSQL
- **Backend**: FastAPI with Uvicorn
- **Frontend**: Next.js with TypeScript
- **Containerization**: Docker & Docker Compose

## Getting Started

1. Copy the environment variables:
   ```bash
   cp .env.example .env
   ```

2. Update the `.env` file with your actual values.

3. Start the services:
   ```bash
   docker-compose up -d
   ```

4. Access the applications:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8000
   - API Documentation: http://localhost:8000/docs

## Development

### Backend Development
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend Development
```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

See `.env.example` for all available environment variables and their descriptions.

