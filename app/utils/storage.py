"""Avatar storage: AWS S3 when configured, else an inline data-URI fallback (dev).

Production uses S3 (the project's chosen object store). When AWS credentials are
absent (local dev), small images are encoded as data URIs so upload still works
end to end without external infrastructure.
"""
import base64
import logging
import uuid

from app.core.config import settings

logger = logging.getLogger(__name__)


def s3_configured() -> bool:
    return bool(settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY and settings.AWS_S3_BUCKET)


def store_avatar(user_id: str, content: bytes, content_type: str) -> str:
    """Return a URL/URI for the stored avatar."""
    if s3_configured():
        import boto3  # imported lazily so the dep is only needed when used

        ext = (content_type.split("/")[-1] or "png").split(";")[0]
        key = f"avatars/{user_id}/{uuid.uuid4().hex}.{ext}"
        client_kwargs = {"region_name": settings.AWS_REGION,
                         "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
                         "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY}
        if settings.S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        s3 = boto3.client("s3", **client_kwargs)
        s3.put_object(Bucket=settings.AWS_S3_BUCKET, Key=key, Body=content,
                      ContentType=content_type)
        base = settings.S3_ENDPOINT_URL or f"https://{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com"
        url = f"{base}/{settings.AWS_S3_BUCKET}/{key}" if settings.S3_ENDPOINT_URL else f"{base}/{key}"
        logger.info("Stored avatar in S3: %s", key)
        return url

    # Dev fallback: inline data URI (kept small by the upload size limit).
    encoded = base64.b64encode(content).decode()
    return f"data:{content_type};base64,{encoded}"
