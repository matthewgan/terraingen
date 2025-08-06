# Terrain Generation API Documentation

## Overview

The Terrain Generation API provides endpoints for generating terrain data for ArduPilot. The API supports both circular and rectangular area generation.

## Base URL

- Development: `http://localhost:8000`
- Production: `https://your-domain.com`

## API Endpoints

### Health Check

**GET** `/api/health`

Returns the health status of the API.

**Response:**
```json
{
  "status": "healthy",
  "version": "2.0.0"
}
```

### Generate Terrain (Circular Area)

**POST** `/api/generate`

Generate terrain data for a circular area around a center point.

**Request Body:**
```json
{
  "lat": 40.7128,
  "lon": -74.0060,
  "radius": 10,
  "version": 3
}
```

**Parameters:**
- `lat` (float): Latitude of center point (-90 to 90)
- `lon` (float): Longitude of center point (-180 to 180)
- `radius` (int): Radius in kilometers (1 to 400)
- `version` (int): Terrain version (1 or 3)

**Response:**
```json
{
  "success": true,
  "uuid": "12345678-1234-1234-1234-123456789abc",
  "download_url": "/userRequestTerrain/12345678-1234-1234-1234-123456789abc.zip",
  "outside_lat": false
}
```

### Generate Terrain (Rectangular Area)

**POST** `/api/generate_rectangle`

Generate terrain data for a rectangular area.

**Request Body:**
```json
{
  "min_lat": 40.0,
  "max_lat": 42.0,
  "min_lon": -74.0,
  "max_lon": -72.0,
  "version": 3
}
```

**Parameters:**
- `min_lat` (float): Minimum latitude (-90 to 90)
- `max_lat` (float): Maximum latitude (-90 to 90)
- `min_lon` (float): Minimum longitude (-180 to 180)
- `max_lon` (float): Maximum longitude (-180 to 180)
- `version` (int): Terrain version (1 or 3)

**Response:**
```json
{
  "success": true,
  "uuid": "12345678-1234-1234-1234-123456789abc",
  "download_url": "/userRequestTerrain/12345678-1234-1234-1234-123456789abc.zip",
  "outside_lat": false
}
```

## Error Responses

**Validation Error (400):**
```json
{
  "detail": [
    {
      "loc": ["body", "lat"],
      "msg": "ensure this value is greater than or equal to -90",
      "type": "value_error.number.not_ge"
    }
  ]
}
```

**Server Error (500):**
```json
{
  "detail": "Internal server error"
}
```

**Rate Limit Exceeded (429):**
```json
{
  "detail": "Rate limit exceeded: 50 per 1 hour"
}
```

## Usage Examples

### cURL Examples

**Generate circular terrain:**
```bash
curl -X POST "http://localhost:8000/api/generate" \
  -H "Content-Type: application/json" \
  -d '{
    "lat": 40.7128,
    "lon": -74.0060,
    "radius": 10,
    "version": 3
  }'
```

**Generate rectangular terrain:**
```bash
curl -X POST "http://localhost:8000/api/generate_rectangle" \
  -H "Content-Type: application/json" \
  -d '{
    "min_lat": 40.0,
    "max_lat": 42.0,
    "min_lon": -74.0,
    "max_lon": -72.0,
    "version": 3
  }'
```

### Python Examples

```python
import requests

# Generate circular terrain
response = requests.post("http://localhost:8000/api/generate", json={
    "lat": 40.7128,
    "lon": -74.0060,
    "radius": 10,
    "version": 3
})

if response.status_code == 200:
    data = response.json()
    if data["success"]:
        print(f"Download URL: {data['download_url']}")
        print(f"UUID: {data['uuid']}")

# Generate rectangular terrain
response = requests.post("http://localhost:8000/api/generate_rectangle", json={
    "min_lat": 40.0,
    "max_lat": 42.0,
    "min_lon": -74.0,
    "max_lon": -72.0,
    "version": 3
})

if response.status_code == 200:
    data = response.json()
    if data["success"]:
        print(f"Download URL: {data['download_url']}")
        print(f"UUID: {data['uuid']}")
```

## Rate Limiting

- **Limit:** 50 requests per hour per IP address
- **Headers:** Rate limit information is included in response headers

## File Download

After successful generation, the terrain data can be downloaded from the provided `download_url`. The file is a ZIP archive containing the terrain data files.

## Legacy Endpoints

The following legacy endpoints are still available for backward compatibility:

- **POST** `/generate` - Form-based circular terrain generation
- **POST** `/generate_rectangle` - Form-based rectangular terrain generation

## Interactive API Documentation

FastAPI provides automatic interactive API documentation:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

## Running the Application

### Development
```bash
python app_fastapi.py
```

### Production with uvicorn
```bash
uvicorn app_fastapi:app --host 0.0.0.0 --port 8000
```

### Production with gunicorn
```bash
gunicorn app_fastapi:app -w 4 -k uvicorn.workers.UvicornWorker
``` 