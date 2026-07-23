"""Object storage: AWS S3 when configured, else an inline data-URI fallback (dev).

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


def store_image(prefix: str, ident: str, content: bytes, content_type: str) -> str:
    """Store an image under `prefix/ident/<uuid>.<ext>` and return its URL/URI."""
    if s3_configured():
        import boto3  # imported lazily so the dep is only needed when used

        ext = (content_type.split("/")[-1] or "png").split(";")[0]
        key = f"{prefix}/{ident}/{uuid.uuid4().hex}.{ext}"
        client_kwargs = {"region_name": settings.AWS_REGION,
                         "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
                         "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY}
        if settings.S3_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        s3 = boto3.client("s3", **client_kwargs)
        s3.put_object(Bucket=settings.AWS_S3_BUCKET, Key=key, Body=content, ContentType=content_type)
        base = settings.S3_ENDPOINT_URL or f"https://{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com"
        url = f"{base}/{settings.AWS_S3_BUCKET}/{key}" if settings.S3_ENDPOINT_URL else f"{base}/{key}"
        logger.info("Stored image in S3: %s", key)
        return url

    # Dev fallback: inline data URI (kept small by the upload size limit).
    return f"data:{content_type};base64,{base64.b64encode(content).decode()}"


_bucket_region_cache: dict[str, str] = {}


def _bucket_region() -> str:
    """The bucket's actual AWS region (auto-detected + cached), so presigned URLs
    are signed for the right region even if AWS_REGION in config is wrong."""
    bucket = settings.AWS_S3_BUCKET
    if bucket in _bucket_region_cache:
        return _bucket_region_cache[bucket]
    region = settings.AWS_REGION or "us-east-1"
    try:
        import boto3
        probe = boto3.client("s3", region_name="us-east-1",
                             aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                             aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
        loc = probe.get_bucket_location(Bucket=bucket).get("LocationConstraint")
        region = loc or "us-east-1"  # us-east-1 reports as None/empty
    except Exception:  # noqa: BLE001
        pass
    _bucket_region_cache[bucket] = region
    return region


def _s3_client():
    import boto3
    from botocore.config import Config
    region = _bucket_region()
    kwargs = {"region_name": region,
              "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
              "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
              "config": Config(signature_version="s3v4")}  # modern presigned URLs (X-Amz-*)
    # Pin the regional endpoint so the presigned URL host matches the signing region
    # (the global s3.amazonaws.com host would trigger a PermanentRedirect).
    kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL or f"https://s3.{region}.amazonaws.com"
    return boto3.client("s3", **kwargs)


def _s3_key(url_or_key: str) -> str | None:
    """Extract the object key from a stored S3 URL (region-agnostic) or accept a bare key."""
    if not url_or_key or url_or_key.startswith("data:"):
        return None
    if url_or_key.startswith("http"):
        marker = ".amazonaws.com/"
        i = url_or_key.find(marker)
        if i == -1:
            pref = f"{settings.S3_ENDPOINT_URL}/{settings.AWS_S3_BUCKET}/" if settings.S3_ENDPOINT_URL else None
            return url_or_key[len(pref):].split("?")[0] if pref and url_or_key.startswith(pref) else None
        rest = url_or_key[i + len(marker):].split("?")[0]
        if rest.startswith(f"{settings.AWS_S3_BUCKET}/"):  # path-style → drop the bucket segment
            rest = rest[len(settings.AWS_S3_BUCKET) + 1:]
        return rest or None
    return url_or_key  # already a bare key


def presign_url(url_or_key: str | None, expires: int = 86400) -> str | None:
    """Temporary signed URL so a private S3 object is viewable in the browser.
    Data URIs / non-S3 URLs pass through unchanged."""
    if not url_or_key or url_or_key.startswith("data:") or not s3_configured():
        return url_or_key
    key = _s3_key(url_or_key)
    if not key:
        return url_or_key
    try:
        return _s3_client().generate_presigned_url(
            "get_object", Params={"Bucket": settings.AWS_S3_BUCKET, "Key": key}, ExpiresIn=expires)
    except Exception:  # noqa: BLE001
        return url_or_key


def store_avatar(user_id: str, content: bytes, content_type: str) -> str:
    """Return a URL/URI for the stored avatar."""
    return store_image("avatars", user_id, content, content_type)


def store_chat_image(user_id: str, content: bytes, content_type: str) -> str:
    """Return a URL/URI for a chat image attachment."""
    return store_image("chat", user_id, content, content_type)


def store_chat_file(user_id: str, content: bytes, content_type: str) -> str:
    """Return a URL/URI for a chat file/document attachment (any type)."""
    return store_image("chat-files", user_id, content, content_type)


def store_group_avatar(conv_id: str, content: bytes, content_type: str) -> str:
    """Return a URL/URI for a group conversation's avatar image."""
    return store_image("chat-groups", conv_id, content, content_type)
