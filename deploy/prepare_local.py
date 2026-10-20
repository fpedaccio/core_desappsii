"""Create local credentials once; never overwrite an existing configuration."""

import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    root = Path(__file__).resolve().parent
    env = root / ".env"
    key_dir = root / "secrets"
    key_path = key_dir / "jwt-private.pem"
    if env.exists() or key_path.exists():
        raise SystemExit("Existing credentials detected. Preserve them; no files were replaced.")
    key_dir.mkdir(mode=0o700, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with key_path.open("xb") as handle:
        handle.write(pem)
    # Compose file secrets are bind-mounted: the non-root container must read it.
    # The host parent directory is private (0700 on Linux).
    os.chmod(key_dir, 0o700)
    os.chmod(key_path, 0o644)
    with env.open("x", encoding="utf-8") as handle:
        handle.write(
            f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n"
            f"RABBITMQ_PASSWORD={secrets.token_urlsafe(32)}\n"
            f"SEED_INITIAL_PASSWORD={secrets.token_urlsafe(24)}\n"
            "CORS_ORIGINS=http://localhost:8080\n"
            "# Set these only after choosing a server/domain:\n"
            "# CORE_DOMAIN=core.your-domain.example\n"
        )
    os.chmod(env, 0o600)
    print("Created local credentials. Do not upload .env, secrets, or seed logs.")


if __name__ == "__main__":
    main()
