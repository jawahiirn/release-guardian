import argparse
import getpass

from sqlalchemy import text

from apps.api.app.main import engine
from packages.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first Release Guardian administrator")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    with engine.begin() as connection:
        if connection.execute(text("SELECT 1 FROM users LIMIT 1")).first() is not None:
            print("Bootstrap already completed; no changes made.")
            return
        password = getpass.getpass("Administrator password (minimum 12 characters): ")
        if len(password) < 12:
            raise SystemExit("Password must contain at least 12 characters.")
        connection.execute(
            text("INSERT INTO users (email, password_hash) VALUES (:email, :password_hash)"),
            {"email": args.email.strip().lower(), "password_hash": hash_password(password)},
        )
    print("Administrator created.")


if __name__ == "__main__":
    main()
