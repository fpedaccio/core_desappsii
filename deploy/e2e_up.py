"""Arranque aislado de la candidata para las pruebas E2E."""

from pathlib import Path

import testing_up

# Solo afecta a este proceso. No cambia el bootstrap general.
testing_up.FRONTEND_REF = "1d8d1b8325767da8926b98325e904d11a6cdfb3d"
testing_up.BACKEND_IMAGE = "muni-core-backend:e2e"
testing_up.FRONTEND_IMAGE = "muni-core-frontend:e2e"


if __name__ == "__main__":
    bootstrap = testing_up.Bootstrap(
        Path(__file__).resolve().parent,
        project="muni-core-testing-e2e",
        port=18083,
    )
    bootstrap.start()
