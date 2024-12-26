from logging.config import fileConfig
from sqlalchemy import engine_from_config, create_engine
from sqlalchemy import pool
from alembic import context
import os
from dotenv import load_dotenv
import sys
from pathlib import Path
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Add the project root directory to Python path
sys.path.append(str(Path(__file__).parent.parent))

from models import Base

load_dotenv()

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def create_database_if_not_exists():
    """Create PostgreSQL database if it doesn't exist"""
    DB_TYPE = os.getenv('DB_TYPE', 'sqlite')
    if DB_TYPE == 'postgres':
        DB_NAME = os.getenv('DB_NAME', 'file_storage')
        try:
            # Connect to PostgreSQL server (to 'postgres' database)
            conn = psycopg2.connect(
                dbname='postgres',
                user=os.getenv('DB_USER', 'postgres'),
                password=os.getenv('DB_PASSWORD', ''),
                host=os.getenv('DB_HOST', 'localhost'),
                port=os.getenv('DB_PORT', '5432')
            )
            conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
            cur = conn.cursor()

            # Check if database exists
            cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{DB_NAME}'")
            exists = cur.fetchone()
            
            if not exists:
                print(f"Creating database {DB_NAME}")
                cur.execute(f'CREATE DATABASE "{DB_NAME}"')
                print(f"Database {DB_NAME} created successfully")
            
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Error creating database: {e}")
            raise

def get_url():
    DB_TYPE = os.getenv('DB_TYPE', 'sqlite')
    if DB_TYPE == 'postgres':
        return (f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
                f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}")
    else:
        DB_NAME = os.getenv('DB_NAME', 'file-storage')
        DATABASE_PATH = os.getenv('DATABASE_PATH')
        if DATABASE_PATH:
            os.makedirs(DATABASE_PATH, exist_ok=True)
            return f"sqlite:///{os.path.join(DATABASE_PATH, f'{DB_NAME}.db')}"
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        os.makedirs(data_dir, exist_ok=True)
        return f"sqlite:///{os.path.join(data_dir, f'{DB_NAME}.db')}"

def include_object(object, name, type_, reflected, compare_to):
    """Filter out unsupported SQLite operations"""
    if type_ == "table":
        return True
        
    # For SQLite, skip ALTER TABLE operations that modify columns
    if context.get_context().dialect.name == "sqlite":
        if type_ == "column" and reflected and compare_to:
            # Skip column modifications for SQLite
            return False
            
    return True

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,  # Add filter
        render_as_batch=True,  # Enable batch operations for SQLite
    )

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    # Create database if it doesn't exist (PostgreSQL only)
    create_database_if_not_exists()

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,  # Add filter
            render_as_batch=True,  # Enable batch operations for SQLite
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
