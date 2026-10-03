from projectctl.cli.app import app
from projectctl.cli.m04 import register_m04
from projectctl.cli.m05 import register_m05

register_m04(app)
register_m05(app)


def main() -> None:
    app()
