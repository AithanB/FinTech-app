import sys
from decimal import Decimal
from zoneinfo import ZoneInfo

import pydantic


def main() -> None:
    print(f"Python: {sys.version.split()[0]}")
    print(f"Pydantic: {pydantic.__version__}")
    print(f"Decimal: {Decimal('0.1') + Decimal('0.2')}")
    print(f"Timezone: {ZoneInfo('Asia/Almaty').key}")
    print("Environment is ready.")


if __name__ == "__main__":
    main()