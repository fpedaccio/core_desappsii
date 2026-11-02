"""Start the isolated local performance environment."""

from pathlib import Path

import testing_up

PROJECT = "muni-core-testing-performance"
PORT = 18087
FRONTEND = "d00f07b71aaa61d27adcb179ec5a3180e9e78874"



class PerformanceBootstrap(testing_up.Bootstrap):
    """Apply the tested API process configuration only to performance."""

    def compose(self, *args: str, capture: bool = False) -> str:
        override = self.deploy / "compose.performance.yaml"
        if not override.is_file():
            raise RuntimeError("Missing performance Compose override")
        return super().compose("-f", str(override), *args, capture=capture)


def main():
    if testing_up.FRONTEND_REF != FRONTEND:
        raise RuntimeError("Unexpected frontend pin")
    testing_up.BACKEND_IMAGE = "muni-core-backend:performance"
    testing_up.FRONTEND_IMAGE = "muni-core-frontend:performance"
    PerformanceBootstrap(
        Path(__file__).resolve().parent,
        project=PROJECT,
        port=PORT,
    ).start()


if __name__ == "__main__":
    main()
