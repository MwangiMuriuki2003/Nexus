"""Nexus CLI entry point.

Subcommands: `setup`, `serve`, `ui` (ui is the default). The legacy
`python -m Nexus --headless [--host H] [--port P]` form still works and maps
to `serve`.
"""
import argparse
import sys
from pathlib import Path

from Nexus.config import ensure_dirs, settings

VERSION = "0.1.0"


def setup_nexus():
    """Initialize data directories and download model if missing."""
    ensure_dirs()
    print(f"Data directory: {settings.data_dir}")
    print("Initializing databases...")
    # TODO: init_sqlite_schemas()
    # TODO: init_chromadb()
    model_path = settings.model_dir / settings.gguf_filename
    if not model_path.exists():
        print(f"Model not found at {model_path}")
        print("Please download from Hugging Face:")
        print(f"  huggingface-cli download {settings.model_name} {settings.gguf_filename} --local-dir {settings.model_dir}")
    else:
        print(f"Model ready: {model_path}")
    print("Setup complete.")


def run_ui():
    """Launch the PyQt6 desktop application."""
    from PyQt6.QtWidgets import QApplication
    from Nexus.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m Nexus", description="Nexus — Private Desktop Brain")
    parser.add_argument("--version", action="version", version=f"Nexus {VERSION}")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("setup", help="create data directories and check the model")

    serve_parser = subparsers.add_parser("serve", help="run the headless web server")
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (0.0.0.0/any non-loopback address requires --token)",
    )
    serve_parser.add_argument("--port", type=int, default=8080, help="Port to listen on")
    serve_parser.add_argument(
        "--token",
        default=None,
        help="Bearer token required on /api/* (mandatory for non-loopback hosts)",
    )

    subparsers.add_parser("ui", help="launch the desktop app (default)")

    # Legacy flags: `python -m Nexus --headless --host ... --port ...`.
    # Separate dests so they never collide with the `serve` subcommand's own flags.
    parser.add_argument("--headless", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--host", dest="legacy_host", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--port", dest="legacy_port", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--token", dest="legacy_token", default=None, help=argparse.SUPPRESS)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command
    if command is None:
        command = "serve" if args.headless else "ui"

    if command == "setup":
        setup_nexus()
    elif command == "serve":
        from Nexus.web.server import serve

        host = getattr(args, "host", None) or args.legacy_host or "127.0.0.1"
        port = getattr(args, "port", None) or args.legacy_port or 8080
        token = getattr(args, "token", None) or args.legacy_token
        serve(host=host, port=port, token=token)
    else:
        run_ui()


if __name__ == "__main__":
    main()
