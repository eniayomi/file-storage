# Secure File Storage Service

A secure web application for storing and sharing files with customizable url.

## Features
- 🔐 Secure authentication system with session timeout
- 📁 Custom link names for each uploaded file
- 🔄 File versioning support
- 🌐 Public/Private file sharing options
- ⏲️ 30-minute session timeout for security
- 🔗 Easy-to-share download links
- 🗑️ File management (upload, delete, visibility toggle)
- 📱 Responsive design
- ⚡ Session timeout warning (10 minutes before expiry)
- 📂 Configurable upload directory
- 🔄 Automatic directory creation
- 🐳 Docker support

## Technical Stack
- FastAPI (Python web framework)
- SQLite (Database)
- HTTP Basic Auth (Authentication)
- Jinja2 Templates (Frontend)
- Custom middleware for session management
- Docker & Docker Compose

## Installation

### Method 1: Traditional Setup
1. Clone the repository
2. Create a `.env` file with your credentials:
   ```
   ADMIN_USERNAME=your_username
   ADMIN_PASSWORD=your_password
   UPLOAD_DIR=/path/to/custom/uploads  # Optional - defaults to "uploads" folder
   ```
3. Install dependencies: `pip install -r requirements.txt`
4. Run the application: `uvicorn main:app --reload`

### Method 2: Docker Setup
1. Clone the repository
2. Create a `.env` file with your credentials (same as above)
3. Build and run with Docker Compose:
   ```bash
   docker-compose up -d --build
   ```

Docker-specific commands:
- Start application: `docker-compose up -d`
- View logs: `docker-compose logs -f`
- Stop application: `docker-compose down`
- Rebuild after changes: `docker-compose up -d --build`

The Docker setup includes:
- Persistent volume for uploads
- Persistent volume for database
- Automatic container restart
- Health checks
- Secure non-root user configuration

## Security Features
- Protected routes with authentication
- Session timeout after 30 minutes of inactivity
- Secure file handling
- Environment variable configuration
- Public/Private file access control
- Session warning notifications

## Usage
- Upload files with custom link names
- Toggle file visibility between public and private
- Share download links with others
- Manage files through the web interface
- Automatic version control for files with same custom link name
- Configure custom upload directory through environment variables
- Automatic creation of upload directory if it doesn't exist