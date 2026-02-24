# Bala Travel Agent

AI-powered personal travel planning web app. Enter complex natural language flight queries, get ranked results with explanations.

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 20+
- API keys: Amadeus, SerpAPI, Anthropic

### Setup

```bash
# Clone and enter project
cd bala-travel-agent

# Copy environment template
cp .env.example .env
# Edit .env with your API keys

# Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker-compose up --build
```

## Architecture

```
React SPA (Vite) --> FastAPI Backend --> Amadeus API + SerpAPI + Claude API
```

- **Frontend:** React 18 + Vite + Tailwind CSS
- **Backend:** Python FastAPI + Amadeus SDK + Anthropic SDK
- **AI:** Claude for NL parsing + result ranking with explanations
- **Hosting:** Railway

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Authenticate with password |
| POST | `/api/auth/logout` | End session |
| POST | `/api/search` | New flight search |
| POST | `/api/search/{id}/refine` | Refine results conversationally |
| GET | `/api/search/{id}` | Get search results |
| GET | `/api/health` | Health check |
