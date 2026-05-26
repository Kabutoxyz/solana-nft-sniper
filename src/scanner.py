"""NFT Scanner — discover new NFT mints on Solana via Helius & DexScreener APIs."""

import asyncio
import logging
import time
from typing import List, Optional, Dict, Any

import httpx

from src.filters import NFTCandidate

logger = logging.getLogger(__name__)


class NFTScanner:
    """Scan for new NFT mints using Helius enhanced API and DexScreener."""

    def __init__(self, rpc_url: str, helius_api_key: str = "",
                 helius_enhanced_api: str = "https://api.helius.xyz/v0",
                 dexscreener_api: str = "https://api.dexscreener.com/latest/dex",
                 max_results: int = 50):
        self.rpc_url = rpc_url
        self.helius_api_key = helius_api_key
        self.helius_api = helius_enhanced_api
        self.dexscreener_api = dexscreener_api
        self.max_results = max_results
        self._seen_mints: set[str] = set()

    async def get_recent_mints(self, limit: int = 50) -> List[NFTCandidate]:
        """Fetch recently minted NFTs from the Solana blockchain."""
        candidates = []
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Method 1: Use Helius getAssetsByCreator or DAS API
                helius_candidates = await self._scan_helius_assets(client, limit)
                candidates.extend(helius_candidates)

                # Method 2: Query recent NFT transactions via RPC
                rpc_candidates = await self._scan_rpc_mints(client, limit)
                candidates.extend(rpc_candidates)
        except Exception as e:
            logger.error(f"Scanner error: {e}")

        # Deduplicate
        unique = []
        for c in candidates:
            if c.mint_address not in self._seen_mints:
                self._seen_mints.add(c.mint_address)
                unique.append(c)

        logger.info(f"Scanner found {len(unique)} new NFT candidates")
        return unique[:self.max_results]

    async def _scan_helius_assets(self, client: httpx.AsyncClient,
                                   limit: int) -> List[NFTCandidate]:
        """Use Helius DAS (Digital Asset Standard) API to find recent assets."""
        if not self.helius_api_key:
            logger.warning("No Helius API key configured, skipping Helius scan")
            return []

        candidates = []
        # Use Helius DAS getAssetsByGroup for known collections or search
        url = f"{self.helius_api}/assets?api-key={self.helius_api_key}"

        # Search for recently created assets
        search_url = f"https://mainnet.helius-rpc.com/?api-key={self.helius_api_key}"
        payload = {
            "jsonrpc": "2.0",
            "id": "search",
            "method": "searchAssets",
            "params": {
                "limit": limit,
                "sortBy": {"sortBy": "created", "sortDirection": "desc"},
                "creatorVerified": True,
            },
        }
        try:
            resp = await client.post(search_url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("result", {}).get("items", [])
                for item in items:
                    content = item.get("content", {}).get("metadata", {})
                    creators = item.get("creators", [])
                    grouping = item.get("grouping", [])
                    collection_id = ""
                    for g in grouping:
                        if g.get("group_key") == "collection":
                            collection_id = g.get("group_value", "")

                    candidate = NFTCandidate(
                        name=content.get("name", "Unknown"),
                        mint_address=item.get("id", ""),
                        collection_address=collection_id,
                        creators=[
                            {"address": c.get("address", ""),
                             "share": c.get("share", 0),
                             "verified": c.get("verified", False)}
                            for c in creators
                        ],
                        verified=item.get("creatorVerified", False),
                        metadata=content,
                    )
                    candidates.append(candidate)
            else:
                logger.warning(f"Helius search failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"Helius DAS API error: {e}")

        return candidates

    async def _scan_rpc_mints(self, client: httpx.AsyncClient,
                               limit: int) -> List[NFTCandidate]:
        """Query Solana RPC for recent token mints with metadata."""
        candidates = []
        metaplex_program = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"

        # Get recent signatures for the Metaplex metadata program
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [metaplex_program, {"limit": min(limit, 25)}],
        }
        try:
            resp = await client.post(self.rpc_url, json=payload, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"RPC signatures query failed: {resp.status_code}")
                return candidates

            data = resp.json()
            sigs = data.get("result", [])
            logger.debug(f"Found {len(sigs)} recent Metaplex transactions")

            # Fetch details for a subset
            for sig_info in sigs[:10]:
                sig = sig_info.get("signature")
                if not sig:
                    continue
                candidate = await self._parse_mint_transaction(client, sig)
                if candidate:
                    candidates.append(candidate)
                await asyncio.sleep(0.2)  # Rate limit
        except Exception as e:
            logger.error(f"RPC mint scan error: {e}")

        return candidates

    async def _parse_mint_transaction(self, client: httpx.AsyncClient,
                                       signature: str) -> Optional[NFTCandidate]:
        """Parse a Solana transaction to extract NFT mint details."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        }
        try:
            resp = await client.post(self.rpc_url, json=payload, timeout=30)
            if resp.status_code != 200:
                return None
            data = resp.json()
            tx = data.get("result")
            if not tx or tx.get("meta", {}).get("err") is not None:
                return None

            # Extract account keys and instructions
            message = tx.get("transaction", {}).get("message", {})
            account_keys = message.get("accountKeys", [])

            # Look for createMetadataAccount instruction
            instructions = message.get("instructions", [])
            for ix in instructions:
                program_id = ix.get("programId", "")
                if "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s" in str(program_id):
                    # This is a metadata creation — likely an NFT mint
                    accounts = ix.get("accounts", [])
                    mint_address = accounts[0] if len(accounts) > 0 else ""
                    if mint_address and mint_address not in self._seen_mints:
                        return NFTCandidate(
                            name="Pending Metadata",
                            mint_address=mint_address,
                            metadata={"raw_signature": signature},
                        )
        except Exception as e:
            logger.debug(f"Transaction parse error for {signature[:20]}...: {e}")
        return None

    async def get_collection_info(self, collection_address: str) -> Dict[str, Any]:
        """Fetch collection details from DexScreener or Helius."""
        info = {}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Try DexScreener
                url = f"{self.dexscreener_api}/tokens/{collection_address}"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        pair = pairs[0]
                        info = {
                            "name": pair.get("baseToken", {}).get("name", ""),
                            "symbol": pair.get("baseToken", {}).get("symbol", ""),
                            "price_usd": pair.get("priceUsd", "0"),
                            "volume_24h": pair.get("volume", {}).get("h24", 0),
                            "liquidity": pair.get("liquidity", {}).get("usd", 0),
                        }
        except Exception as e:
            logger.debug(f"Collection info fetch error: {e}")
        return info

    async def scan_loop(self, interval: int = 30, callback=None) -> None:
        """Continuously scan for new mints at a given interval."""
        logger.info(f"Starting scan loop (interval={interval}s)")
        while True:
            try:
                candidates = await self.get_recent_mints()
                if candidates and callback:
                    await callback(candidates)
            except Exception as e:
                logger.error(f"Scan loop error: {e}")
            await asyncio.sleep(interval)
