"""
Database client singleton.

Returns a local PostgresClient when DATABASE_URL is set (local dev with Docker),
otherwise returns a Supabase client (production).

The PostgresClient implements the same query builder interface as supabase-py,
so all service code works unchanged in both environments.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_supabase_client():
    """Return a cached database client instance.

    When DATABASE_URL is set, returns a local PostgresClient (psycopg2-backed)
    that is compatible with the Supabase query builder interface.
    Otherwise returns a real Supabase client for production use.

    Raises:
        ValueError: If required environment variables are missing.
        Exception: If the client cannot be initialised.
    """
    if os.getenv("DATABASE_URL"):
        from db.postgres_client import get_postgres_client
        return get_postgres_client()

    from supabase import Client, create_client

    url: str | None = os.getenv("SUPABASE_URL")
    key: str | None = os.getenv("SUPABASE_SERVICE_KEY")

    if not url:
        raise ValueError("SUPABASE_URL environment variable is not set.")
    if not key:
        raise ValueError("SUPABASE_SERVICE_KEY environment variable is not set.")

    logger.info("Initialising Supabase client for URL: %s", url)
    client: Client = create_client(url, key)
    return client
