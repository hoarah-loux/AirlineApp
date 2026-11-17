"""
MongoDB-backed storage for roster payloads (NoSQL option).

This is intentionally small and optional:
- If the user selects backend="nosql", we store the roster payload in MongoDB
  and keep only a reference (nosql_ref) in the SQL database.
- If MongoDB isn't reachable, we raise a ValueError explaining how to run it.

Configuration (env vars):
- MONGO_URI (default: mongodb://localhost:27017)
- MONGO_DB  (default: airlineapp)
- MONGO_COLLECTION (default: rosters)
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from bson import ObjectId


_CLIENT: Optional[MongoClient] = None


def _get_client() -> MongoClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT

    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    # serverSelectionTimeoutMS keeps failures fast/clear during demos
    _CLIENT = MongoClient(uri, serverSelectionTimeoutMS=2000)
    return _CLIENT


def _get_collection():
    client = _get_client()
    db_name = os.getenv("MONGO_DB", "airlineapp")
    col_name = os.getenv("MONGO_COLLECTION", "rosters")
    return client[db_name][col_name]


def _ensure_available() -> None:
    try:
        _get_client().admin.command("ping")
    except ServerSelectionTimeoutError as exc:
        raise ValueError(
            "NoSQL backend selected but MongoDB is not reachable. "
            "Run MongoDB (e.g., `docker compose up -d mongodb`) and set MONGO_URI if needed."
        ) from exc


def store_payload(payload: Dict[str, Any]) -> str:
    """
    Store a roster payload document in MongoDB and return its _id as a string.
    """
    _ensure_available()
    col = _get_collection()
    res = col.insert_one({"payload": payload})
    return str(res.inserted_id)


def load_payload(ref: str) -> Optional[Dict[str, Any]]:
    """
    Load a roster payload document from MongoDB by string ref (_id).
    """
    if not ref:
        return None
    _ensure_available()
    col = _get_collection()
    doc = col.find_one({"_id": ObjectId(ref)})
    if not doc:
        return None
    return doc.get("payload")
