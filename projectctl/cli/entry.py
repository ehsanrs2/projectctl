from projectctl.cli.app import app
from projectctl.cli.m04 import register_m04
from projectctl.cli.m05 import register_m05
from projectctl.cli.m11 import register_m11
from projectctl.cli.m12a import register_m12a
from projectctl.cli.m13 import register_m13
from projectctl.cli.m40b import register_m40b
from projectctl.cli.m41a import register_m41a
from projectctl.cli.m50 import register_m50

register_m04(app)
register_m05(app)
register_m11(app)
register_m12a(app)
register_m13(app)
register_m40b(app)
register_m41a(app)
register_m50(app)


def main() -> None:
    app()
