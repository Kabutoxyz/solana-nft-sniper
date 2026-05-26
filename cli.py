"""CLI entry point for Solana NFT Sniper — subcommands: scan, monitor, mint, snipe."""

import argparse
import asyncio
import logging
import signal
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Settings
from src.scanner import NFTScanner
from src.monitor import ProgramMonitor
from src.mint import NFTMinter
from src.filters import NFTFilter, NFTCandidate, rugcheck_heuristic
from src.notifier import Notifier

logger = logging.getLogger("sniper")


def setup_logging(level: str, log_file: str = "") -> None:
    """Configure logging for the application."""
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def build_settings(args) -> Settings:
    """Build Settings from args and config file."""
    settings = Settings().load()
    if hasattr(args, "rpc") and args.rpc:
        settings.rpc_url = args.rpc
    if hasattr(args, "helius_key") and args.helius_key:
        settings.helius_api_key = args.helius_key
    if hasattr(args, "wallet") and args.wallet:
        settings.wallet_keypair_path = args.wallet
    if hasattr(args, "max_price") and args.max_price is not None:
        settings.max_mint_price_sol = args.max_price
    if hasattr(args, "telegram_token") and args.telegram_token:
        settings.telegram_bot_token = args.telegram_token
    if hasattr(args, "telegram_chat") and args.telegram_chat:
        settings.telegram_chat_id = args.telegram_chat
    return settings


async def cmd_scan(args, settings: Settings) -> None:
    """Scan for new NFT mints."""
    scanner = NFTScanner(
        rpc_url=settings.effective_rpc,
        helius_api_key=settings.helius_api_key,
        helius_enhanced_api=settings.helius_enhanced_api,
        dexscreener_api=settings.dexscreener_api,
        max_results=settings.max_results,
    )
    nft_filter = NFTFilter(
        min_collection_size=settings.min_collection_size,
        max_collection_size=settings.max_collection_size,
        max_mint_price_sol=settings.max_mint_price_sol,
        min_supply_remaining=settings.min_supply_remaining,
        require_verified_creator=settings.require_verified_creator,
    )
    notifier = Notifier(
        telegram_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        desktop=settings.desktop_notifications,
    )

    logger.info("Scanning for new NFT mints...")
    candidates = await scanner.get_recent_mints(limit=args.limit)

    if not candidates:
        logger.info("No new NFT candidates found.")
        return

    logger.info(f"Found {len(candidates)} candidates, applying filters...")
    passed = nft_filter.filter_batch(candidates)

    for candidate in passed:
        # Run rugcheck
        rug_ok, rug_warnings = rugcheck_heuristic(candidate)
        status = "✅ PASS" if rug_ok else f"⚠️ WARNINGS: {'; '.join(rug_warnings)}"
        print(f"\n{'='*60}")
        print(f"  Name: {candidate.name}")
        print(f"  Mint: {candidate.mint_address}")
        print(f"  Collection: {candidate.collection_address or 'N/A'}")
        print(f"  Price: {candidate.price_sol} SOL")
        print(f"  Supply: {candidate.remaining_supply}/{candidate.total_supply}")
        print(f"  Verified: {candidate.verified}")
        print(f"  Rugcheck: {status}")
        print(f"{'='*60}")

        if settings.notify_on_match:
            await notifier.notify_new_mint(
                candidate.name, candidate.mint_address,
                candidate.price_sol, candidate.total_supply,
            )

    print(f"\nResults: {len(passed)}/{len(candidates)} passed filters.")


async def cmd_monitor(args, settings: Settings) -> None:
    """Monitor candy machines in real-time via WebSocket."""
    notifier = Notifier(
        telegram_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        desktop=settings.desktop_notifications,
    )
    nft_filter = NFTFilter(
        max_mint_price_sol=settings.max_mint_price_sol,
        require_verified_creator=settings.require_verified_creator,
    )

    candy_ids = []
    if args.candy_machine:
        candy_ids = args.candy_machine

    monitor = ProgramMonitor(
        websocket_url=settings.websocket_url,
        rpc_url=settings.effective_rpc,
        candy_machine_ids=candy_ids,
    )

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()

    async def on_mint_detected(event):
        logger.info(f"Mint event detected: {event.get('type')} — {event.get('account', 'N/A')}")
        if settings.notify_on_match:
            await notifier.send(
                "NFT Mint Detected",
                f"Type: {event.get('type')}\nAccount: {event.get('account', 'N/A')}",
            )

    monitor.on_mint_detected = on_mint_detected

    # Also poll candy machines if specified
    async def poll_loop():
        if not candy_ids:
            return
        while True:
            for cm_id in candy_ids:
                state = await monitor.poll_candy_machine(cm_id, settings.effective_rpc)
                remaining = state.get("remaining", "?")
                logger.info(f"Candy Machine {cm_id[:12]}... — Remaining: {remaining}")
            await asyncio.sleep(30)

    logger.info(f"Starting monitor (watching {len(candy_ids)} candy machines)...")
    logger.info(f"WebSocket: {settings.websocket_url}")

    await asyncio.gather(monitor.start(), poll_loop())


async def cmd_mint(args, settings: Settings) -> None:
    """Mint an NFT from a candy machine."""
    notifier = Notifier(
        telegram_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        desktop=settings.desktop_notifications,
    )

    minter = NFTMinter(
        rpc_url=settings.effective_rpc,
        wallet_keypair_path=settings.wallet_keypair_path,
        wallet_private_key=settings.wallet_private_key,
        max_priority_fee_lamports=settings.max_priority_fee_lamports,
        timeout=settings.mint_timeout_seconds,
        retry_attempts=settings.retry_attempts,
        retry_delay=settings.retry_delay_seconds,
    )

    price_lamports = int(args.price * 1_000_000_000)
    logger.info(f"Minting from {args.candy_machine} (price: {args.price} SOL)...")

    result = await minter.mint(args.candy_machine, price_lamports)
    minter.cleanup()

    if result.get("success"):
        sig = result.get("signature", "")
        mint_addr = result.get("mint_address", "")
        logger.info(f"✅ Mint successful! Tx: {sig}")
        logger.info(f"   NFT Mint Address: {mint_addr}")
        if settings.notify_on_mint:
            await notifier.notify_mint_success(mint_addr, sig)
    else:
        error = result.get("error", "Unknown error")
        logger.error(f"❌ Mint failed: {error}")
        if settings.notify_on_mint:
            await notifier.notify_mint_failure(args.candy_machine, error)


async def cmd_snipe(args, settings: Settings) -> None:
    """Combined mode: monitor + auto-filter + auto-mint (the full sniper)."""
    notifier = Notifier(
        telegram_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        desktop=settings.desktop_notifications,
    )
    nft_filter = NFTFilter(
        min_collection_size=settings.min_collection_size,
        max_collection_size=settings.max_collection_size,
        max_mint_price_sol=settings.max_mint_price_sol,
        min_supply_remaining=settings.min_supply_remaining,
        require_verified_creator=settings.require_verified_creator,
    )
    scanner = NFTScanner(
        rpc_url=settings.effective_rpc,
        helius_api_key=settings.helius_api_key,
        max_results=settings.max_results,
    )
    minter = NFTMinter(
        rpc_url=settings.effective_rpc,
        wallet_keypair_path=settings.wallet_keypair_path,
        wallet_private_key=settings.wallet_private_key,
        max_priority_fee_lamports=settings.max_priority_fee_lamports,
        timeout=settings.mint_timeout_seconds,
        retry_attempts=settings.retry_attempts,
    )

    candy_ids = args.candy_machine or []
    auto_mint = not args.dry_run

    logger.info("🎯 SNIPE MODE ACTIVE")
    logger.info(f"   Monitoring: {len(candy_ids)} candy machines")
    logger.info(f"   Max price: {settings.max_mint_price_sol} SOL")
    logger.info(f"   Auto-mint: {'ENABLED' if auto_mint else 'DRY RUN'}")

    monitor = ProgramMonitor(
        websocket_url=settings.websocket_url,
        rpc_url=settings.effective_rpc,
        candy_machine_ids=candy_ids,
    )

    async def on_opportunity(candidate: NFTCandidate):
        """Handle a detected minting opportunity."""
        passed, reasons = nft_filter.apply(candidate)
        if not passed:
            logger.debug(f"Filtered out: {candidate.name} — {'; '.join(reasons)}")
            return

        rug_ok, rug_warnings = rugcheck_heuristic(candidate)
        logger.info(f"🎯 OPPORTUNITY: {candidate.name} ({candidate.mint_address})")
        if rug_warnings:
            logger.warning(f"   Rugcheck warnings: {'; '.join(rug_warnings)}")

        await notifier.notify_new_mint(
            candidate.name, candidate.mint_address,
            candidate.price_sol, candidate.total_supply,
        )

        if auto_mint and candidate.candy_machine_id:
            price_lamports = int(candidate.price_sol * 1_000_000_000)
            result = await minter.mint(candidate.candy_machine_id, price_lamports)
            if result.get("success"):
                await notifier.notify_mint_success(
                    result.get("mint_address", ""),
                    result.get("signature", ""),
                )
            else:
                await notifier.notify_mint_failure(
                    candidate.mint_address,
                    result.get("error", "Unknown"),
                )

    async def on_ws_event(event):
        """Handle WebSocket events."""
        logger.info(f"Event: {event.get('type')} — account: {event.get('account', 'N/A')}")

    monitor.on_mint_detected = on_ws_event

    # Run scanner loop + WebSocket monitor concurrently
    async def scanner_loop():
        while True:
            try:
                candidates = await scanner.get_recent_mints()
                for c in candidates:
                    await on_opportunity(c)
            except Exception as e:
                logger.error(f"Scanner error: {e}")
            await asyncio.sleep(settings.scan_interval_seconds)

    await asyncio.gather(monitor.start(), scanner_loop())


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Solana NFT Sniper — automated NFT mint monitoring and sniping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--rpc", help="Solana RPC URL", default=None)
    parser.add_argument("--helius-key", help="Helius API key", default=None)
    parser.add_argument("--wallet", help="Wallet keypair JSON path", default=None)
    parser.add_argument("--log-level", help="Log level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-file", help="Log file path", default="")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scan subcommand
    scan_parser = subparsers.add_parser("scan", help="Scan for new NFT mints")
    scan_parser.add_argument("--limit", type=int, default=50, help="Max results")
    scan_parser.add_argument("--max-price", type=float, default=None,
                             help="Max mint price in SOL")
    scan_parser.add_argument("--telegram-token", help="Telegram bot token", default=None)
    scan_parser.add_argument("--telegram-chat", help="Telegram chat ID", default=None)

    # monitor subcommand
    mon_parser = subparsers.add_parser("monitor", help="Real-time WebSocket monitor")
    mon_parser.add_argument("--candy-machine", nargs="*", default=[],
                            help="Candy machine IDs to watch")
    mon_parser.add_argument("--telegram-token", help="Telegram bot token", default=None)
    mon_parser.add_argument("--telegram-chat", help="Telegram chat ID", default=None)

    # mint subcommand
    mint_parser = subparsers.add_parser("mint", help="Mint an NFT")
    mint_parser.add_argument("candy_machine", help="Candy machine ID")
    mint_parser.add_argument("--price", type=float, default=0,
                             help="Mint price in SOL")
    mint_parser.add_argument("--telegram-token", help="Telegram bot token", default=None)
    mint_parser.add_argument("--telegram-chat", help="Telegram chat ID", default=None)

    # snipe subcommand
    snipe_parser = subparsers.add_parser("snipe", help="Full sniper: monitor + filter + auto-mint")
    snipe_parser.add_argument("--candy-machine", nargs="*", default=[],
                              help="Candy machine IDs to watch")
    snipe_parser.add_argument("--max-price", type=float, default=None,
                              help="Max mint price in SOL")
    snipe_parser.add_argument("--dry-run", action="store_true",
                              help="Monitor only, do not auto-mint")
    snipe_parser.add_argument("--telegram-token", help="Telegram bot token", default=None)
    snipe_parser.add_argument("--telegram-chat", help="Telegram chat ID", default=None)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    settings = build_settings(args)
    setup_logging(args.log_level, args.log_file or settings.log_file)

    cmd_map = {
        "scan": cmd_scan,
        "monitor": cmd_monitor,
        "mint": cmd_mint,
        "snipe": cmd_snipe,
    }

    handler = cmd_map[args.command]
    try:
        asyncio.run(handler(args, settings))
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
