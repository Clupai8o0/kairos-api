import uuid


def cuid() -> str:
    """Generate a CUID-like unique identifier using UUID4 with a 'c' prefix."""
    return "c" + uuid.uuid4().hex
