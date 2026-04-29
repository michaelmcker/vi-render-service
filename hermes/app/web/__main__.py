"""`python -m app.web` — uvicorn entrypoint for the systemd unit."""
import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    bind = os.environ.get("HERMES_WEB_BIND", "127.0.0.1")
    port = int(os.environ.get("HERMES_WEB_PORT", "8080"))
    uvicorn.run("app.web.main:app", host=bind, port=port, log_level="info",
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
