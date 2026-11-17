"""Start the isolated integrated testing candidate."""
from pathlib import Path

from testing_up import Bootstrap

if __name__ == "__main__":
    Bootstrap(
        Path(__file__).resolve().parent,
        project="muni-core-testing-integrated",
        port=18088,
    ).start()
