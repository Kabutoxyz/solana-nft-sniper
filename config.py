"""Configuration settings for Solana NFT Sniper."""

import os
from dataclasses import dataclass, field
from typing import Optional
import json

CONFIG_FILE = os.path.expanduser("~/.solana-nft-sniper/config.json")


@dataclass
class Settings:
    # RPC endpoints
    rpc_url: str = "https://solana.lava.build"
    helius_api_key: str = ""
    helius_rpc_url: str = ""

    # Wallet
    wallet_keypair_path: str = os.path.expanduser("~/.config/solana/id.json")
    wallet_private_key: str = ""  # base58 encoded, alternative to file

    # Monitoring
    websocket_url: str = "wss://solana.lava.build"
    candy_machine_program: str = "cndyAnrLdpjq1SspUz8Bsq3yAgFDiPhT79pJ6Nz1SmL"
    metaplex_metadata_program: str = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"

    # Scanner
    dexscreener_api: str = "https://api.dexscreener.com/latest/dex"
    helius_enhanced_api: str = "https://api.helius.xyz/v0"
    scan_interval_seconds: int = 30
    max_results: int = 50

    # Filters
    min_collection_size: int = 100
    max_collection_size: int = 100000
    max_mint_price_sol: float = 5.0
    min_supply_remaining: int = 1
    require_verified_creator: bool = True
    require_rugcheck_pass: bool = True

    # Minting
    max_priority_fee_lamports: int = 100_000
    mint_timeout_seconds: int = 30
    retry_attempts: int = 3
    retry_delay_seconds: float = 1.0

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    desktop_notifications: bool = True
    notify_on_match: bool = True
    notify_on_mint: bool = True

    # Logging
    log_level: str = "INFO"
    log_file: str = "sniper.log"

    def load(self) -> "Settings":
        """Load settings from config file, overlaying env vars."""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
            for key, val in data.items():
                if hasattr(self, key):
                    setattr(self, key, val)

        # Environment variable overrides
        env_map = {
            "SOLANA_RPC_URL": "rpc_url",
            "HELIUS_API_KEY": "helius_api_key",
            "WALLET_KEYPAIR_PATH": "wallet_keypair_path",
            "WALLET_PRIVATE_KEY": "wallet_private_key",
            "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
            "TELEGRAM_CHAT_ID": "telegram_chat_id",
            "WEBSOCKET_URL": "websocket_url",
        }
        for env_var, attr in env_map.items():
            val = os.environ.get(env_var)
            if val:
                setattr(self, attr, val)

        # Derive Helius RPC URL
        if self.helius_api_key and not self.helius_rpc_url:
            self.helius_rpc_url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"

        return self

    def save(self) -> None:
        """Save current settings to config file."""
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        data = {}
        for key, val in self.__dict__.items():
            if not key.startswith("_"):
                data[key] = val
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)

    @property
    def effective_rpc(self) -> str:
        """Return Helius RPC if available, else default."""
        return self.helius_rpc_url if self.helius_rpc_url else self.rpc_url
