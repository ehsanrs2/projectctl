from projectctl.cli.app import app
from projectctl.cli.m04 import register_m04

register_m04(app)


def main() -> None:
    app()
