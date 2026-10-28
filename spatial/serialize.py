import math
from datetime import datetime

from bson import ObjectId


def to_jsonable(value):
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def public_document(document: dict | None) -> dict | None:
    if document is None:
        return None
    result = to_jsonable(document)
    if "_id" in result:
        result["_id"] = str(result["_id"])
    return result
