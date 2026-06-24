"""Allow the `.local` special-use TLD in email addresses.

Pydantic's EmailStr delegates to `email-validator`, which by default rejects
reserved/special-use domains such as `.local` (RFC 6762). For local/development
identities like `admin@dailyactivity.local` we whitelist `local` so the seeded
dev admin can authenticate. Import this module before any EmailStr validation
runs (it is imported by app.core.config, which loads first).

This is a development convenience. Production deployments should use a real,
deliverable domain for accounts.
"""
try:
    import email_validator

    if "local" in getattr(email_validator, "SPECIAL_USE_DOMAIN_NAMES", []):
        email_validator.SPECIAL_USE_DOMAIN_NAMES.remove("local")
except Exception:  # noqa: BLE001 - never block startup over this convenience
    pass
