from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException, Depends, status
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
import secrets
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
from contextlib import contextmanager

# Load environment variables
load_dotenv()

# Define constants with environment variable support
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")  # Use custom path from .env or default to "uploads"
SESSION_TIMEOUT = 30 * 60  # 30 minutes in seconds
USERNAME = os.getenv("ADMIN_USERNAME")
PASSWORD = os.getenv("ADMIN_PASSWORD")

# Ensure required environment variables are set
if not USERNAME or not PASSWORD:
    raise Exception("Missing required environment variables. Please check your .env file.")

last_activity = {}

def ensure_upload_dir():
    """Create the upload directory if it doesn't exist"""
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        print(f"Upload directory confirmed: {os.path.abspath(UPLOAD_DIR)}")
    except Exception as e:
        raise Exception(f"Failed to create upload directory: {e}")

# Database connection management
@contextmanager
def get_db():
    db = sqlite3.connect('database.db')
    try:
        yield db
    finally:
        db.close()

def init_database():
    """Initialize the database and create tables if they don't exist"""
    try:
        # Ensure upload directory exists
        ensure_upload_dir()

        # Initialize the database schema
        with get_db() as db:
            cursor = db.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS links (
                    custom_link TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_public BOOLEAN DEFAULT 0
                )
            ''')
            db.commit()
    except Exception as e:
        print(f"Database initialization error: {e}")
        raise

# Initialize database
init_database()

app = FastAPI()

# Create a custom security class that allows skipping auth
class OptionalHTTPBasic(HTTPBasic):
    async def __call__(self, request: Request) -> Optional[HTTPBasicCredentials]:
        try:
            return await super().__call__(request)
        except HTTPException:
            return None

security = OptionalHTTPBasic()

def verify_credentials_or_public(
    request: Request,
    custom_link: str,
    credentials: Optional[HTTPBasicCredentials] = Depends(security)
):
    # First check if the file is public
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute("SELECT is_public FROM links WHERE custom_link = ?", (custom_link,))
        result = cursor.fetchone()
        
        if result and result[0]:  # If file exists and is public
            return True
        
        # If private, require and verify credentials
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required for private files",
                headers={"WWW-Authenticate": "Basic"},
            )
        
        correct_username = secrets.compare_digest(credentials.username, USERNAME)
        correct_password = secrets.compare_digest(credentials.password, PASSWORD)
        
        if not (correct_username and correct_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Basic"},
            )
        
        return True

# Keep your original verify_credentials for admin-only routes
def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    
    correct_username = secrets.compare_digest(credentials.username, USERNAME)
    correct_password = secrets.compare_digest(credentials.password, PASSWORD)
    
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials

# Template setup
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

class SessionTimeoutMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip session check for public files and login
        if "download" in request.url.path:
            path_parts = request.url.path.split('/')
            if len(path_parts) >= 3:  # Ensure we have enough parts in the path
                custom_link = path_parts[-2]
                with get_db() as db:
                    cursor = db.cursor()
                    cursor.execute("SELECT is_public FROM links WHERE custom_link = ?", (custom_link,))
                    result = cursor.fetchone()
                    if result and result[0]:  # If file is public
                        return await call_next(request)

        # Check for credentials
        auth = request.headers.get('Authorization')
        if auth:
            current_time = time.time()
            
            if auth in last_activity:
                time_elapsed = current_time - last_activity[auth]
                if time_elapsed > SESSION_TIMEOUT:
                    last_activity.pop(auth, None)
                    return RedirectResponse(
                        url="/logout",
                        status_code=303
                    )
            
            last_activity[auth] = current_time

        return await call_next(request)

# Add the middleware to the app
app.add_middleware(SessionTimeoutMiddleware)

@app.get("/")
def home(request: Request, credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute("SELECT custom_link, file_path, created_at, is_public FROM links")
        files = cursor.fetchall()
        
        files_info = []
        for link, path, created_at, is_public in files:
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f} KB"
                else:
                    size_str = f"{size/(1024*1024):.1f} MB"
                    
                files_info.append({
                    "custom_link": link,
                    "filename": os.path.basename(path),
                    "size": size_str,
                    "created_at": datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M:%S"),
                    "is_public": is_public,
                    "download_url": f"/download/{link}"
                })
        
        return templates.TemplateResponse(
            "index.html", 
            {"request": request, "files": files_info}
        )

@app.post("/upload/")
async def upload_file(
    request: Request,
    custom_link: str = Form(...),
    file: UploadFile = File(...),
    is_public: bool = Form(False),
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    with get_db() as db:
        cursor = db.cursor()
        current_time = datetime.now().isoformat()
        
        # Check if custom_link already exists
        cursor.execute("SELECT file_path FROM links WHERE custom_link = ?", (custom_link,))
        existing = cursor.fetchone()
        
        if existing:
            # Create a versioned custom_link for the existing file
            version = 1
            while True:
                versioned_link = f"{custom_link}-v{version}"
                cursor.execute("SELECT file_path FROM links WHERE custom_link = ?", (versioned_link,))
                if not cursor.fetchone():
                    break
                version += 1
                
            # Rename the existing entry to include version
            cursor.execute(
                "UPDATE links SET custom_link = ? WHERE custom_link = ?",
                (versioned_link, custom_link)
            )
            db.commit()
        
        # Save the new file
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        contents = await file.read()
        with open(file_path, "wb") as f:
            f.write(contents)

        # Insert the new file with the original custom_link
        cursor.execute(
            "INSERT INTO links (custom_link, file_path, created_at, is_public) VALUES (?, ?, ?, ?)",
            (custom_link, file_path, current_time, is_public)
        )
        db.commit()

        return RedirectResponse(url=f"/download/{custom_link}", status_code=303)

@app.get("/download/{custom_link}")
def download_page(
    request: Request,
    custom_link: str,
    auth: bool = Depends(verify_credentials_or_public)
):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute("SELECT file_path FROM links WHERE custom_link = ?", (custom_link,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="Link not found")

        file_path = result[0]
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")

        return templates.TemplateResponse(
            "download.html",
            {
                "request": request,
                "file_path": os.path.basename(file_path),
                "download_link": f"/download/{custom_link}/file",
                "custom_link": custom_link
            }
        )

@app.get("/download/{custom_link}/file")
async def serve_file(
    request: Request,
    custom_link: str,
    auth: bool = Depends(verify_credentials_or_public)
):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute("SELECT file_path FROM links WHERE custom_link = ?", (custom_link,))
        result = cursor.fetchone()

        if not result:
            raise HTTPException(status_code=404, detail="File not found")

        file_path = result[0]
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(file_path)

@app.get("/files")
def list_files(request: Request):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute("SELECT custom_link, file_path FROM links")
        files = cursor.fetchall()
        files = [{"custom_link": link, "filename": os.path.basename(path)} for link, path in files]
        return templates.TemplateResponse("files.html", {"request": request, "files": files})

@app.post("/delete/{custom_link}")
async def delete_file(
    custom_link: str,
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    # Get file path before deleting from database
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute("SELECT file_path FROM links WHERE custom_link = ?", (custom_link,))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="File not found")
        
        file_path = result[0]
        
        # Delete from database
        cursor.execute("DELETE FROM links WHERE custom_link = ?", (custom_link,))
        db.commit()
        
        # Delete actual file if it exists
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return RedirectResponse(url="/", status_code=303)

@app.post("/toggle-visibility/{custom_link}")
async def toggle_visibility(
    custom_link: str,
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute("SELECT is_public FROM links WHERE custom_link = ?", (custom_link,))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="File not found")
        
        new_status = not result[0]  # Toggle the current status
        
        cursor.execute(
            "UPDATE links SET is_public = ? WHERE custom_link = ?",
            (new_status, custom_link)
        )
        db.commit()
        
        return RedirectResponse(url="/", status_code=303)

@app.get("/logout")
def logout(request: Request):
    response = RedirectResponse(url="/")
    response.headers["WWW-Authenticate"] = "Basic"
    response.status_code = 401
    
    # Clear session data
    auth = request.headers.get('Authorization')
    if auth and auth in last_activity:
        last_activity.pop(auth)
    
    return response

# Add session status endpoint (optional, for debugging)
@app.get("/session-status")
def session_status(request: Request, credentials: HTTPBasicCredentials = Depends(verify_credentials)):
    auth = request.headers.get('Authorization')
    if auth in last_activity:
        elapsed = time.time() - last_activity[auth]
        remaining = max(0, SESSION_TIMEOUT - elapsed)
        return {
            "session_active": True,
            "time_remaining": f"{int(remaining/60)} minutes {int(remaining%60)} seconds"
        }
    return {"session_active": False}