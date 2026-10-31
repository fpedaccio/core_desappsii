"""Start the isolated local performance environment."""

from pathlib import Path

import testing_up

PROJECT = "muni-core-testing-performance"
PORT = 18087
FRONTEND = "6353a6dfd3613d17ade5564b96b7e09dfec70573"


def main():
    if testing_up.FRONTEND_REF != FRONTEND:
        raise RuntimeError("Unexpected frontend pin")
    testing_up.BACKEND_IMAGE = "muni-core-backend:performance"
    testing_up.FRONTEND_IMAGE = "muni-core-frontend:performance"
    testing_up.Bootstrap(
        Path(__file__).resolve().parent,
        project=PROJECT,
        port=PORT,
    ).start()


if __name__ == "__main__":
    main()
