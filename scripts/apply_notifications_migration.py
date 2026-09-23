"""Compatibility wrapper; use migrate_database.py for ordered migration tracking."""

from migrate_database import migrate_to


def main() -> int:
    return migrate_to('002')


if __name__ == "__main__":
    raise SystemExit(main())