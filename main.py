from fastapi import FastAPI, Request, Form, File, UploadFile, HTTPException, Depends, status
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import Optional
import secrets
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
import time
import mimetypes
from sqlalchemy.orm import Session
from models import Link
from database import get_db

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

# Ensure upload directory exists
ensure_upload_dir()

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
    file_password: str = Form(None),
    credentials: Optional[HTTPBasicCredentials] = Depends(security)
):
    with get_db() as db:
        cursor = db.cursor()
        cursor.execute("SELECT is_public, file_password FROM links WHERE custom_link = ?", (custom_link,))
        result = cursor.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail="Link not found")
        
        is_public, stored_password = result
        
        # If file is public, allow access
        if is_public:
            return True
            
        # Check admin credentials first
        if credentials:
            correct_username = secrets.compare_digest(credentials.username, USERNAME)
            correct_password = secrets.compare_digest(credentials.password, PASSWORD)
            if correct_username and correct_password:
                return True
        
        # If not admin and file has password, handle password check
        if stored_password:
            if file_password:
                if secrets.compare_digest(str(stored_password), str(file_password)):
                    return True
            else:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="password_required"
                )
        
        # If all checks fail, require admin authentication
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

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
                    link = db.query(Link).filter(Link.custom_link == custom_link).first()
                    if link and link.is_public:  # If file is public
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
        # Get all links using SQLAlchemy
        files = db.query(Link).all()
        
        files_info = []
        for link in files:
            if os.path.exists(link.file_path):
                size = os.path.getsize(link.file_path)
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024 * 1024:
                    size_str = f"{size/1024:.1f} KB"
                else:
                    size_str = f"{size/(1024*1024):.1f} MB"
                    
                files_info.append({
                    "custom_link": link.custom_link,
                    "filename": os.path.basename(link.file_path),
                    "size": size_str,
                    "created_at": link.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "is_public": link.is_public,
                    "download_url": f"/download/{link.custom_link}"
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
    file_password: str = Form(None),
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    try:
        with get_db() as db:
            # Check if custom_link already exists
            existing = db.query(Link).filter(Link.custom_link == custom_link).first()
            
            if existing:
                # Create a versioned custom_link for the existing file
                version = 1
                while True:
                    versioned_link = f"{custom_link}-v{version}"
                    if not db.query(Link).filter(Link.custom_link == versioned_link).first():
                        break
                    version += 1
                    
                # Rename the existing entry to include version
                existing.custom_link = versioned_link
                db.commit()
            
            # Save the new file
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            contents = await file.read()
            with open(file_path, "wb") as f:
                f.write(contents)

            # Create new link with hashed password
            new_link = Link(
                custom_link=custom_link,
                file_path=file_path,
                is_public=is_public,
                file_password=Link.hash_password(file_password)
            )
            db.add(new_link)
            db.commit()

            return RedirectResponse(
                url=f"/file/{custom_link}?success=File uploaded successfully",
                status_code=303
            )
    except Exception as e:
        return RedirectResponse(
            url=f"/?error=Upload failed: {str(e)}",
            status_code=303
        )

@app.get("/file/{custom_link}")
async def file_page(
    request: Request,
    custom_link: str,
    credentials: Optional[HTTPBasicCredentials] = Depends(security)
):
    """Show file info and download/preview options"""
    with get_db() as db:
        link = db.query(Link).filter(Link.custom_link == custom_link).first()
        
        if not link:
            raise HTTPException(status_code=404, detail="File not found")
            
        # Check if user is admin
        is_admin = False
        if credentials:
            try:
                correct_username = secrets.compare_digest(credentials.username, USERNAME)
                correct_password = secrets.compare_digest(credentials.password, PASSWORD)
                is_admin = correct_username and correct_password
            except:
                is_admin = False
        
        return templates.TemplateResponse(
            "download.html",
            {
                "request": request,
                "custom_link": custom_link,
                "file_path": os.path.basename(link.file_path),
                "requires_password": bool(link.file_password),
                "download_link": f"/download/{custom_link}/file",
                "preview_link": f"/preview/{custom_link}/file",
                "is_admin": is_admin
            }
        )

@app.get("/download/{custom_link}")
@app.post("/download/{custom_link}")
async def serve_file(
    request: Request,
    custom_link: str,
    file_password: str = Form(None),
    credentials: Optional[HTTPBasicCredentials] = Depends(security)
):
    """Serve the actual file download"""
    with get_db() as db:
        link = db.query(Link).filter(Link.custom_link == custom_link).first()

        if not link:
            raise HTTPException(status_code=404, detail="File not found")

        # If file is public, serve it
        if link.is_public:
            return FileResponse(
                link.file_path,
                filename=os.path.basename(link.file_path),
                media_type='application/octet-stream'
            )

        # Check admin credentials
        if credentials:
            correct_username = secrets.compare_digest(credentials.username, USERNAME)
            correct_password = secrets.compare_digest(credentials.password, PASSWORD)
            if correct_username and correct_password:
                return FileResponse(
                    link.file_path,
                    filename=os.path.basename(link.file_path),
                    media_type='application/octet-stream'
                )

        # For password-protected files, redirect to file info page if no password provided
        if link.file_password and not file_password:
            return RedirectResponse(
                url=f"/file/{custom_link}",
                status_code=303
            )

        # Verify file password if provided
        if link.file_password and file_password:
            if link.verify_password(file_password):
                return FileResponse(
                    link.file_path,
                    filename=os.path.basename(link.file_path),
                    media_type='application/octet-stream'
                )
            else:
                return RedirectResponse(
                    url=f"/file/{custom_link}?error=incorrect_password",
                    status_code=303
                )

        # If no password protection but not admin, require admin auth
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

@app.get("/files")
def list_files(request: Request):
    with get_db() as db:
        files = db.query(Link).all()
        files_info = [{"custom_link": link.custom_link, "filename": os.path.basename(link.file_path)} for link in files]
        return templates.TemplateResponse("files.html", {"request": request, "files": files_info})

@app.post("/delete/{custom_link}")
async def delete_file(
    custom_link: str,
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    with get_db() as db:
        link = db.query(Link).filter(Link.custom_link == custom_link).first()
        
        if not link:
            return RedirectResponse(
                url="/?error=File not found",
                status_code=303
            )
            
        # Delete file from filesystem
        try:
            if os.path.exists(link.file_path):
                os.remove(link.file_path)
        except Exception as e:
            return RedirectResponse(
                url=f"/?error=Error deleting file: {str(e)}",
                status_code=303
            )
            
        # Delete database entry
        db.delete(link)
        db.commit()
        
        return RedirectResponse(
            url="/?success=File deleted successfully",
            status_code=303
        )

@app.post("/toggle-visibility/{custom_link}")
async def toggle_visibility(
    custom_link: str,
    credentials: HTTPBasicCredentials = Depends(verify_credentials)
):
    with get_db() as db:
        link = db.query(Link).filter(Link.custom_link == custom_link).first()
        
        if not link:
            return RedirectResponse(
                url="/?error=File not found",
                status_code=303
            )
        
        link.is_public = not link.is_public
        db.commit()
        
        status_text = "public" if link.is_public else "private"
        return RedirectResponse(
            url=f"/file/{custom_link}?success=File visibility changed to {status_text}",
            status_code=303
        )

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

@app.get("/preview/{custom_link}")
async def preview_file(
    request: Request,
    custom_link: str,
    file_password: str = Form(None),
    credentials: Optional[HTTPBasicCredentials] = Depends(security)
):
    with get_db() as db:
        link = db.query(Link).filter(Link.custom_link == custom_link).first()

        if not link:
            raise HTTPException(status_code=404, detail="File not found")
        
        # If file is public, serve it
        if link.is_public:
            return FileResponse(
                link.file_path,
                headers={"Content-Disposition": "inline"}
            )

        # Check admin credentials
        if credentials:
            correct_username = secrets.compare_digest(credentials.username, USERNAME)
            correct_password = secrets.compare_digest(credentials.password, PASSWORD)
            if correct_username and correct_password:
                return FileResponse(
                    link.file_path,
                    headers={"Content-Disposition": "inline"}
                )

        # For password-protected files, redirect to file info page if no password provided
        if link.file_password and not file_password:
            return RedirectResponse(
                url=f"/file/{custom_link}",
                status_code=303
            )

        # Verify file password if provided
        if link.file_password and file_password:
            if secrets.compare_digest(str(link.file_password), str(file_password)):
                return FileResponse(
                    link.file_path,
                    headers={"Content-Disposition": "inline"}
                )
            else:
                return RedirectResponse(
                    url=f"/file/{custom_link}?error=incorrect_password",
                    status_code=303
                )

        # If no password protection but not admin, require admin auth
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )