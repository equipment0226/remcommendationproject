# Backend API (Flask + PyMySQL)

## Quick Start

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

## Endpoints

- `GET /api/health`
- `GET /api/filters`
- `GET /api/products?q=&category=&gender=&limit=24&offset=0`
- `POST /api/cart/events`
- `GET /api/recommendation-sql-example`

This API is intentionally SQL-first so you can add recommendation queries with minimal code changes.
