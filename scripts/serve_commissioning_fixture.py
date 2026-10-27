"""Run one isolated qualification service: the implementation library, or a workspace pointed at it.

Only supplied packages are checked and published: since roadmap H8 the library calls no model (no builder, no reviewer). HTTP,
authentication, persistence, independent correctness checks, package isolation and workers are the real product.
"""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=["workspace", "library"])
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--library-url", default="http://127.0.0.1:8768")
    parser.add_argument("--frontend-directory", type=Path)
    args = parser.parse_args()
    os.environ["GRATING_LLM_DISABLED"] = "true"
    if args.role == "library":
        from optimization_framework.implementations.api import create_app
        app = create_app(args.directory / "library")
    else:
        from balsamic.app import create_app
        from optimization_framework.implementations.client import ImplementationClient
        os.environ["GRATING_IMPLEMENTATIONS_TOKEN_FILE"] = str(args.directory.resolve() / "library/service.token")
        app = create_app(args.directory / "workspace", implementation_client=ImplementationClient(args.library_url),
            frontend_directory=args.frontend_directory)
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port, timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
