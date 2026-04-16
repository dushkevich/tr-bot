"""
Wallet manager: USDC balance checks and allowance management on Polygon.
Uses native USDC (NOT USDC.e/MATICUSDCE) — this distinction is critical.
"""
from __future__ import annotations

import logging

from config.settings import settings

logger = logging.getLogger(__name__)

# Polymarket exchange contract on Polygon that needs USDC approval
POLYMARKET_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
# CTF (Conditional Token Framework) Exchange
CTF_EXCHANGE_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

ERC20_ABI = [
    {"inputs": [{"name": "account", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
    {"inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "name": "approve", "outputs": [{"name": "", "type": "bool"}], "stateMutability": "nonpayable", "type": "function"},
    {"inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}], "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "stateMutability": "view", "type": "function"},
]

# Max uint256 — approve unlimited spending
MAX_UINT256 = 2 ** 256 - 1
# Minimum allowance threshold (100M USDC) before we re-approve
MIN_ALLOWANCE = 100_000_000 * 10 ** 6  # 100M USDC in base units (6 decimals)


class WalletManager:
    """
    Manages Polygon wallet interactions: balance, allowances, gas estimates.
    USDC on Polygon has 6 decimals.
    """

    def __init__(self) -> None:
        self._cfg = settings.system
        self._w3 = None
        self._usdc = None

    def _get_web3(self):
        if self._w3 is None:
            from web3 import Web3
            self._w3 = Web3(Web3.HTTPProvider(self._cfg.polygon_rpc_url))
            if not self._w3.is_connected():
                logger.warning("Web3 not connected to Polygon RPC: %s", self._cfg.polygon_rpc_url)
        return self._w3

    def _get_usdc(self):
        if self._usdc is None:
            w3 = self._get_web3()
            self._usdc = w3.eth.contract(
                address=w3.to_checksum_address(self._cfg.usdc_contract_address),
                abi=ERC20_ABI,
            )
        return self._usdc

    async def get_usdc_balance(self) -> float:
        """Returns USDC balance in human-readable units (not base units)."""
        if self._cfg.dry_run:
            logger.debug("Dry run mode — returning mock balance")
            return 500.0  # Mock balance for dry run
        if not self._cfg.poly_funder_address:
            logger.debug("No wallet address configured — returning mock balance")
            return 500.0  # Mock balance for dry run

        try:
            import asyncio
            usdc = self._get_usdc()
            address = self._get_web3().to_checksum_address(self._cfg.poly_funder_address)
            raw_balance = await asyncio.to_thread(
                usdc.functions.balanceOf(address).call
            )
            return raw_balance / 1_000_000  # USDC has 6 decimals
        except Exception as exc:
            logger.error("Failed to fetch USDC balance: %s", exc)
            return 0.0

    async def ensure_allowances(self) -> None:
        """
        Check USDC allowances for Polymarket exchange contracts.
        Re-approves if below threshold. One-time setup, but safe to call regularly.
        """
        if not self._cfg.poly_private_key or not self._cfg.poly_funder_address:
            logger.debug("No wallet keys configured — skipping allowance check")
            return

        import asyncio
        from eth_account import Account

        try:
            w3 = self._get_web3()
            usdc = self._get_usdc()
            address = w3.to_checksum_address(self._cfg.poly_funder_address)
            account = Account.from_key(self._cfg.poly_private_key)

            for spender_name, spender_addr in [
                ("Polymarket Exchange", POLYMARKET_EXCHANGE_ADDRESS),
                ("CTF Exchange", CTF_EXCHANGE_ADDRESS),
            ]:
                spender = w3.to_checksum_address(spender_addr)
                allowance = await asyncio.to_thread(
                    usdc.functions.allowance(address, spender).call
                )

                if allowance < MIN_ALLOWANCE:
                    logger.info("Approving %s for USDC spending...", spender_name)
                    tx = usdc.functions.approve(spender, MAX_UINT256).build_transaction({
                        "from": address,
                        "nonce": w3.eth.get_transaction_count(address),
                        "gas": 100_000,
                        "gasPrice": w3.eth.gas_price,
                        "chainId": 137,
                    })
                    signed = account.sign_transaction(tx)
                    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                    logger.info("%s approval tx: %s", spender_name, tx_hash.hex())
                else:
                    logger.debug("%s allowance OK", spender_name)

        except Exception as exc:
            logger.error("Allowance check/set failed: %s", exc)

    async def get_polygon_gas_estimate(self) -> float:
        """Returns current gas price in Gwei."""
        try:
            import asyncio
            w3 = self._get_web3()
            gas_price_wei = await asyncio.to_thread(lambda: w3.eth.gas_price)
            return gas_price_wei / 1e9  # Convert to Gwei
        except Exception as exc:
            logger.warning("Gas estimate failed: %s", exc)
            return 30.0  # Default to 30 Gwei
