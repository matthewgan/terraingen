import uuid
import os
import sys
import zipfile
import urllib.request
import gzip
from io import BytesIO
import time
import math
from typing import Optional, List
from pathlib import Path

from fastapi import FastAPI, HTTPException, Depends, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field, validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from terrain_gen import add_offset

# Directory of this file
this_path = os.path.dirname(os.path.realpath(__file__))

# Where the user requested tile are stored
output_path = os.path.join(this_path, '..', 'userRequestTerrain')

# Where the tile database is
if "pytest" in sys.modules:
    # If we're in test mode, use remote URL, not local filesystem
    tile_path1 = os.path.join(this_path, '..', 'tilesdat1')
    url_path1 = 'https://terrain.ardupilot.org/tilesdat1/'
    tile_path3 = os.path.join(this_path, '..', 'tilesdat3')
    url_path3 = 'https://terrain.ardupilot.org/tilesdat3/'
else:
    tile_path3 = os.path.join('/mnt/terrain_data/data/tilesdat3')
    tile_path1 = os.path.join('/mnt/terrain_data/data/tilesdat1')
    url_path1 = None
    url_path3 = None

# Create FastAPI app
app = FastAPI(
    title="Terrain Generation API",
    description="API for generating terrain data for ArduPilot",
    version="2.0.0"
)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount static files
app.mount("/userRequestTerrain", StaticFiles(directory=output_path), name="static")

# Templates
templates = Jinja2Templates(directory="templates")

# Pydantic models for API requests
class GenerateRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90, description="Latitude")
    lon: float = Field(..., ge=-180, le=180, description="Longitude")
    radius: int = Field(..., ge=1, le=400, description="Radius in kilometers")
    version: int = Field(..., description="Terrain version (1 or 3)")
    
    @validator('version')
    def validate_version(cls, v):
        if v not in [1, 3]:
            raise ValueError('Version must be 1 or 3')
        return v

class GenerateRectangleRequest(BaseModel):
    min_lat: float = Field(..., ge=-90, le=90, description="Minimum latitude")
    max_lat: float = Field(..., ge=-90, le=90, description="Maximum latitude")
    min_lon: float = Field(..., ge=-180, le=180, description="Minimum longitude")
    max_lon: float = Field(..., ge=-180, le=180, description="Maximum longitude")
    version: int = Field(..., description="Terrain version (1 or 3)")
    
    @validator('version')
    def validate_version(cls, v):
        if v not in [1, 3]:
            raise ValueError('Version must be 1 or 3')
        return v
    
    @validator('max_lat')
    def validate_lat_range(cls, v, values):
        if 'min_lat' in values and v <= values['min_lat']:
            raise ValueError('max_lat must be greater than min_lat')
        return v
    
    @validator('max_lon')
    def validate_lon_range(cls, v, values):
        if 'min_lon' in values and v <= values['min_lon']:
            raise ValueError('max_lon must be greater than min_lon')
        return v

# Pydantic models for API responses
class GenerateResponse(BaseModel):
    success: bool
    uuid: str
    download_url: Optional[str] = None
    outside_lat: Optional[bool] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    version: str

def clamp(n, smallest, largest):
    return max(smallest, min(n, largest))

def getDatFile(lat, lon):
    '''Get file'''
    if lat < 0:
        NS = 'S'
    else:
        NS = 'N'
    if lon < 0:
        EW = 'W'
    else:
        EW = 'E'
    return "%c%02u%c%03u.DAT.gz" % (NS, min(abs(int(lat)), 99), EW, min(abs(int(lon)), 999))

def compressFiles(fileList, uuidkey, version):
    # create a zip file comprised of dat.gz tiles
    zipthis = os.path.join(output_path, uuidkey + '.zip')

    # create output dirs if needed
    try:
        os.makedirs(output_path)
    except OSError:
        pass
    version = int(version)
    if version == 1:
        url_path = url_path1
        try:
            os.makedirs(tile_path1)
        except OSError:
            pass
    elif version == 3:
        url_path = url_path3
        try:
            os.makedirs(tile_path3)
        except OSError:
            pass

    print("compressFiles: version=%u url_path=%s" % (version, url_path))
            
    try:
        with zipfile.ZipFile(zipthis, 'w') as terrain_zip:
            for fn in fileList:
                if not os.path.exists(fn) and url_path != None:
                    #download if required
                    print("Downloading " + os.path.basename(fn))
                    g = urllib.request.urlopen(url_path +
                                               os.path.basename(fn))
                    print("Downloaded " + os.path.basename(fn))
                    with open(fn, 'b+w') as f:
                        f.write(g.read())

                # need to decompress file and pass to zip
                with gzip.open(fn, 'r') as f_in:
                    myio = BytesIO(f_in.read())
                    print("Decomp " + os.path.basename(fn))

                    # and add file to zip
                    terrain_zip.writestr(os.path.basename(fn)[:-3], myio.read(),
                                         compress_type=zipfile.ZIP_DEFLATED)

    except Exception as ex:
        print("Unexpected error: {0}".format(ex))
        return False

    return True

# Web routes (HTML)
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/generate", response_class=HTMLResponse)
async def generate_page(request: Request):
    return templates.TemplateResponse("generate.html", {"request": request})

# API routes
@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(status="healthy", version="2.0.0")

@app.post("/api/generate", response_model=GenerateResponse)
@limiter.limit("50/hour")
async def generate_api(request: Request, generate_req: GenerateRequest):
    """Generate terrain data for a circular area"""
    try:
        lat = generate_req.lat
        lon = generate_req.lon
        radius = generate_req.radius
        version = generate_req.version
        
        print("Generate API: %.9f %.9f %.3f version=%u" % (lat, lon, radius, version))

        # UUID for this terrain generation
        uuidkey = str(uuid.uuid1())

        # Flag for if user wanted a tile outside +-84deg latitude
        outsideLat = None

        # get a list of files required to cover area
        filelist = []
        done = set()
        
        format = "4.1"
        
        if version == 1:
            tile_path = tile_path1
        else:
            tile_path = tile_path3

        for dx in range(-radius, radius):
            for dy in range(-radius, radius):
                (lat2, lon2) = add_offset(lat*1e7, lon*1e7, dx*1000.0, dy*1000.0, format)
                lat_int = int(math.floor(lat2 * 1.0e-7))
                lon_int = int(math.floor(lon2 * 1.0e-7))
                tag = (lat_int, lon_int)
                if tag in done:
                    continue
                done.add(tag)
                # make sure tile is inside the 84deg lat limit
                if abs(lat_int) <= 84:
                    filelist.append(os.path.join(tile_path, getDatFile(lat_int, lon_int)))
                else:
                    outsideLat = True

        # remove duplicates
        filelist = list(dict.fromkeys(filelist))
        print(filelist)

        #compress
        success = compressFiles(filelist, uuidkey, version)

        # as a cleanup, remove any generated terrain older than 24H
        for f in os.listdir(output_path):
            if os.stat(os.path.join(output_path, f)).st_mtime < time.time() - 24 * 60 * 60:
                print("Removing old file: " + str(os.path.join(output_path, f)))
                os.remove(os.path.join(output_path, f))

        if success:
            print("Generated " + "/terrain/" + uuidkey + ".zip")
            return GenerateResponse(
                success=True,
                uuid=uuidkey,
                download_url=f"/userRequestTerrain/{uuidkey}.zip",
                outside_lat=outsideLat
            )
        else:
            print("Failed " + "/terrain/" + uuidkey + ".zip")
            return GenerateResponse(
                success=False,
                uuid=uuidkey,
                error="Cannot generate terrain"
            )
            
    except Exception as e:
        print(f"Error in generate_api: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate_rectangle", response_model=GenerateResponse)
@limiter.limit("50/hour")
async def generate_rectangle_api(request: Request, rectangle_req: GenerateRectangleRequest):
    """Generate terrain data for a rectangular area"""
    try:
        min_lat = rectangle_req.min_lat
        max_lat = rectangle_req.max_lat
        min_lon = rectangle_req.min_lon
        max_lon = rectangle_req.max_lon
        version = rectangle_req.version
        
        print("Generate Rectangle API: %.9f-%.9f lat, %.9f-%.9f lon, version=%u" % (min_lat, max_lat, min_lon, max_lon, version))

        # UUID for this terrain generation
        uuidkey = str(uuid.uuid1())

        # Flag for if user wanted a tile outside +-84deg latitude
        outsideLat = None

        # get a list of files required to cover rectangular area
        filelist = []
        done = set()
        
        format = "4.1"
        
        if version == 1:
            tile_path = tile_path1
        else:
            tile_path = tile_path3

        # Calculate the step size for tile coverage (approximately 1 degree)
        lat_step = 1.0
        lon_step = 1.0
        
        # Iterate through the rectangular area
        lat = min_lat
        while lat <= max_lat:
            lon = min_lon
            while lon <= max_lon:
                lat_int = int(math.floor(lat))
                lon_int = int(math.floor(lon))
                tag = (lat_int, lon_int)
                if tag in done:
                    lon += lon_step
                    continue
                done.add(tag)
                # make sure tile is inside the 84deg lat limit
                if abs(lat_int) <= 84:
                    filelist.append(os.path.join(tile_path, getDatFile(lat_int, lon_int)))
                else:
                    outsideLat = True
                lon += lon_step
            lat += lat_step

        # remove duplicates
        filelist = list(dict.fromkeys(filelist))
        print(filelist)

        #compress
        success = compressFiles(filelist, uuidkey, version)

        # as a cleanup, remove any generated terrain older than 24H
        for f in os.listdir(output_path):
            if os.stat(os.path.join(output_path, f)).st_mtime < time.time() - 24 * 60 * 60:
                print("Removing old file: " + str(os.path.join(output_path, f)))
                os.remove(os.path.join(output_path, f))

        if success:
            print("Generated " + "/terrain/" + uuidkey + ".zip")
            return GenerateResponse(
                success=True,
                uuid=uuidkey,
                download_url=f"/userRequestTerrain/{uuidkey}.zip",
                outside_lat=outsideLat
            )
        else:
            print("Failed " + "/terrain/" + uuidkey + ".zip")
            return GenerateResponse(
                success=False,
                uuid=uuidkey,
                error="Cannot generate terrain"
            )
            
    except Exception as e:
        print(f"Error in generate_rectangle_api: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Legacy form-based routes (for backward compatibility)
@app.post("/generate")
async def generate_form(
    request: Request,
    lat: float = Form(...),
    lon: float = Form(..., alias="long"),
    radius: int = Form(...),
    version: int = Form(...)
):
    """Legacy form-based generate endpoint"""
    try:
        # Validate input
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180) or version not in [1, 3]:
            return templates.TemplateResponse("generate.html", {
                "request": request,
                "error": "Error with input"
            })
        
        radius = clamp(radius, 1, 400)
        
        # Create request object and call API
        generate_req = GenerateRequest(lat=lat, lon=lon, radius=radius, version=version)
        response = await generate_api(request, generate_req)
        
        if response.success:
            return templates.TemplateResponse("generate.html", {
                "request": request,
                "urlkey": response.download_url,
                "uuidkey": response.uuid,
                "outsideLat": response.outside_lat
            })
        else:
            return templates.TemplateResponse("generate.html", {
                "request": request,
                "error": response.error,
                "uuidkey": response.uuid
            })
            
    except Exception as e:
        return templates.TemplateResponse("generate.html", {
            "request": request,
            "error": "Error with input"
        })

@app.post("/generate_rectangle")
async def generate_rectangle_form(
    request: Request,
    min_lat: float = Form(...),
    max_lat: float = Form(...),
    min_lon: float = Form(...),
    max_lon: float = Form(...),
    version: int = Form(...)
):
    """Legacy form-based generate rectangle endpoint"""
    try:
        # Validate input
        if not (-90 <= min_lat <= 90) or not (-90 <= max_lat <= 90) or \
           not (-180 <= min_lon <= 180) or not (-180 <= max_lon <= 180) or \
           version not in [1, 3] or min_lat >= max_lat or min_lon >= max_lon:
            return templates.TemplateResponse("generate.html", {
                "request": request,
                "error": "Error with rectangle input parameters"
            })
        
        # Create request object and call API
        rectangle_req = GenerateRectangleRequest(
            min_lat=min_lat, max_lat=max_lat,
            min_lon=min_lon, max_lon=max_lon,
            version=version
        )
        response = await generate_rectangle_api(request, rectangle_req)
        
        if response.success:
            return templates.TemplateResponse("generate.html", {
                "request": request,
                "urlkey": response.download_url,
                "uuidkey": response.uuid,
                "outsideLat": response.outside_lat
            })
        else:
            return templates.TemplateResponse("generate.html", {
                "request": request,
                "error": response.error,
                "uuidkey": response.uuid
            })
            
    except Exception as e:
        return templates.TemplateResponse("generate.html", {
            "request": request,
            "error": "Error with rectangle input parameters"
        })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 