#!/usr/bin/env python3
"""
CLI authentication tool for eeroVista.

Use this for headless setups where web UI is not accessible.

Usage:
    python cli_auth.py

Or from within Docker container:
    docker compose exec eerovista python cli_auth.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import ensure_data_directory, get_settings
from src.eero_client import EeroClientWrapper
from src.utils.database import get_db_context, init_database


def main():
    """Run CLI authentication flow."""
    print("=" * 60)
    print("eeroVista CLI Authentication")
    print("=" * 60)
    print()

    # Ensure database exists
    ensure_data_directory()
    init_database()

    # Get database session and client
    with get_db_context() as db:
        client = EeroClientWrapper(db)

        # Check if already authenticated
        if client.is_authenticated():
            print("✓ Already authenticated!")
            account = client.get_account()
            if account:
                print(f"  Account: {account.get('email', 'Unknown')}")
            print()
            print("To re-authenticate, clear tokens first:")
            print("  1. Stop the container")
            print("  2. Delete /data/eerovista.db")
            print("  3. Start the container and run this script again")
            return

        print("Step 1: Enter Phone Number")
        print("-" * 60)
        phone = input("Phone number (with country code, e.g., +1234567890): ").strip()

        if not phone:
            print("✗ Phone number required")
            sys.exit(1)

        print()
        print(f"Sending verification code to {phone}...")
        result = client.login_phone(phone)

        if not result.get("success"):
            print(f"✗ Error: {result.get('message')}")
            sys.exit(1)

        print(f"✓ {result.get('message')}")
        print()

        print("Step 2: Enter Verification Code")
        print("-" * 60)
        code = input("6-digit code from SMS: ").strip()

        if not code or len(code) != 6:
            print("✗ Invalid code format")
            sys.exit(1)

        print()
        print("Verifying code...")
        result = client.login_verify(code)

        if not result.get("success"):
            print(f"✗ Error: {result.get('message')}")
            sys.exit(1)

        print(f"✓ {result.get('message')}")
        print()

        # Verify by getting account
        account = client.get_account()
        if account:
            print("=" * 60)
            print("Authentication Successful!")
            print("=" * 60)
            print(f"Account: {account.get('email', 'Unknown')}")
            networks = client.get_networks()
            if networks:
                print(f"Networks: {len(networks)}")
                for network in networks:
                    print(f"  - {network.get('name', 'Unknown')}")
            print()
            print("You can now access the web UI at http://localhost:8080")
        else:
            print("✗ Authentication succeeded but couldn't fetch account info")
            sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAuthentication cancelled")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        sys.exit(1)
