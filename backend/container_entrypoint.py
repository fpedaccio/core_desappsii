"""Load the mounted signing key before importing the application."""

import os
import sys
from pathlib import Path


def main() -> None:
    key_file = os.environ.get("JWT_PRIVATE_KEY_FILE")
    if key_file:
        os.environ["JWT_PRIVATE_KEY"] = Path(key_file).read_text(encoding="utf-8")
    if os.environ.get("ENVIRONMENT", "").lower() in {"production", "prod"}:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = serialization.load_pem_private_key(
            os.environ.get("JWT_PRIVATE_KEY", "").replace("\\n", "\n").encode(),
            password=None,
        )
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 2048:
            raise RuntimeError("Production requires an RSA key of at least 2048 bits.")
        if os.environ.get("RABBITMQ_URL", "").startswith("memory"):
            raise RuntimeError("Production containers require a real RabbitMQ broker.")
    if len(sys.argv) < 2:
        raise RuntimeError("Missing container command.")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
