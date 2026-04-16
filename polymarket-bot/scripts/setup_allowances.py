"""
One-time setup: approve USDC and CTF token spending for Polymarket exchange contracts.
Run this once before your first live trade.

Usage: python scripts/setup_allowances.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from execution.wallet import WalletManager


async def main():
    print("=" * 60)
    print("Polymarket Bot — One-Time Allowance Setup")
    print("=" * 60)

    cfg = settings.system

    if not cfg.poly_private_key:
        print("ERROR: POLY_PRIVATE_KEY not set in .env")
        sys.exit(1)

    if not cfg.poly_funder_address:
        print("ERROR: POLY_FUNDER_ADDRESS not set in .env")
        sys.exit(1)

    print(f"Wallet: {cfg.poly_funder_address}")
    print(f"USDC contract: {cfg.usdc_contract_address}")
    print()
    print("This will send 2 approval transactions on Polygon (~$0.02 in gas total).")

    confirm = input("Proceed? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        sys.exit(0)

    wallet = WalletManager()
    print("\nChecking and setting allowances...")
    await wallet.ensure_allowances()
    print("\nDone! You can now run the bot in live mode.")
    print("Remember: Start with DRY_RUN=true to validate the pipeline first.")


if __name__ == "__main__":
    asyncio.run(main())
