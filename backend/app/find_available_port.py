import socket

from app.config import get_settings


def find_available_port(preferred_port: int, attempts: int = 20) -> int:
    for port in range(preferred_port, min(preferred_port + attempts, 65536)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No available local port found from {preferred_port}")


def main() -> None:
    print(find_available_port(get_settings().app_port))


if __name__ == "__main__":
    main()
