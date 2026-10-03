from projectctl.cli.app import app
from projectctl.cli.m04 import register_m04
from projectctl.cli.m05 import register_m05
from projectctl.cli.m11 import register_m11

register_m04(app)
register_m05(app)
register_m11(app)


def main() -> None:
    app()
