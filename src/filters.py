"""NFT collection filters — apply criteria to decide whether to snipe."""

import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class NFTCandidate:
    """Represents an NFT collection/mint opportunity."""
    name: str
    mint_address: str
    collection_address: str = ""
    price_sol: float = 0.0
    total_supply: int = 0
    remaining_supply: int = 0
    creators: List[Dict[str, Any]] = None
    verified: bool = False
    candy_machine_id: str = ""
    go_live_date: Optional[int] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.creators is None:
            self.creators = []
        if self.metadata is None:
            self.metadata = {}


class NFTFilter:
    """Filter NFT candidates based on configurable criteria."""

    def __init__(
        self,
        min_collection_size: int = 100,
        max_collection_size: int = 100000,
        max_mint_price_sol: float = 5.0,
        min_supply_remaining: int = 1,
        require_verified_creator: bool = True,
        require_rugcheck_pass: bool = True,
    ):
        self.min_collection_size = min_collection_size
        self.max_collection_size = max_collection_size
        self.max_mint_price_sol = max_mint_price_sol
        self.min_supply_remaining = min_supply_remaining
        self.require_verified_creator = require_verified_creator
        self.require_rugcheck_pass = require_rugcheck_pass

    def apply(self, candidate: NFTCandidate) -> tuple[bool, List[str]]:
        """Apply all filters. Returns (passed, [reasons_for_failure])."""
        failures = []

        # Collection size filter
        if candidate.total_supply > 0:
            if candidate.total_supply < self.min_collection_size:
                failures.append(
                    f"Collection too small: {candidate.total_supply} < {self.min_collection_size}"
                )
            if candidate.total_supply > self.max_collection_size:
                failures.append(
                    f"Collection too large: {candidate.total_supply} > {self.max_collection_size}"
                )

        # Mint price filter
        if candidate.price_sol > self.max_mint_price_sol:
            failures.append(
                f"Mint price too high: {candidate.price_sol} > {self.max_mint_price_sol} SOL"
            )

        # Free mints are suspicious unless expected
        if candidate.price_sol == 0 and self.require_rugcheck_pass:
            failures.append("Free mint — requires rugcheck verification")

        # Supply remaining
        if candidate.remaining_supply < self.min_supply_remaining:
            failures.append(
                f"Insufficient supply remaining: {candidate.remaining_supply} < {self.min_supply_remaining}"
            )

        # Creator verification
        if self.require_verified_creator and candidate.creators:
            has_verified = any(
                c.get("verified", False) for c in candidate.creators
            )
            if not has_verified and not candidate.verified:
                failures.append("No verified creator found")

        passed = len(failures) == 0
        if not passed:
            logger.debug(f"Filter rejected '{candidate.name}': {'; '.join(failures)}")
        else:
            logger.info(f"Filter passed: '{candidate.name}' ({candidate.mint_address})")

        return passed, failures

    def apply_batch(self, candidates: List[NFTCandidate]) -> List[tuple[NFTCandidate, bool, List[str]]]:
        """Apply filters to a batch of candidates."""
        results = []
        for c in candidates:
            passed, reasons = self.apply(c)
            results.append((c, passed, reasons))
        return results

    def filter_batch(self, candidates: List[NFTCandidate]) -> List[NFTCandidate]:
        """Return only passing candidates."""
        return [c for c in candidates if self.apply(c)[0]]


def rugcheck_heuristic(candidate: NFTCandidate) -> tuple[bool, List[str]]:
    """Basic rug-check heuristics based on on-chain data."""
    warnings = []

    # Check if creators have royalty share > 0 (legitimate collections usually do)
    if candidate.creators:
        total_share = sum(c.get("share", 0) for c in candidate.creators)
        if total_share == 0:
            warnings.append("Creator share is 0%")

    # Suspiciously large supply
    if candidate.total_supply > 50000:
        warnings.append(f"Very large supply: {candidate.total_supply}")

    # Free mints with no verification
    if candidate.price_sol == 0 and not candidate.verified:
        warnings.append("Free mint from unverified creator")

    # Check for suspicious metadata patterns
    if candidate.metadata:
        image_url = candidate.metadata.get("image", "")
        if image_url and "ipfs" not in image_url and "arweave" not in image_url and "https" not in image_url:
            warnings.append(f"Non-standard image URL: {image_url[:50]}")

    passed = len(warnings) == 0
    return passed, warnings
