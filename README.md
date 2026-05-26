# 🔫 Solana NFT Sniper

Automated NFT mint monitoring and sniping tool for the Solana blockchain. Scans for new mints, applies configurable filters, and optionally auto-mints NFTs from candy machines.

## Features

- **Scanner** — Discover new NFT mints via Helius DAS API and Solana RPC
- **Real-time Monitor** — WebSocket-based candy machine and Metaplex program monitoring
- **Auto-Mint** — Execute mints via Node.js + @solana/web3.js subprocess
- **Filters** — Collection size, mint price, creator verification, supply remaining, rugcheck heuristics
- **Notifications** — Desktop (notify-send/osascript) and Telegram bot alerts
- **Snipe Mode** — Combined monitor + filter + auto-mint in a single command

## Prerequisites

- Python 3.10+
- Node.js 18+ with `@solana/web3.js` and `bs58` packages
- Solana CLI configured with a funded wallet (optional)

```bash
npm install -g @solana/web3.js bs58
```

## Installation

```bash
git clone https://github.com/nousresearch/solana-nft-sniper.git
cd solana-nft-sniper
pip install -r requirements.txt
```

## Configuration

Create `~/.solana-nft-sniper/config.json` or set environment variables:

```json
{
  "rpc_url": "https://solana.lava.build",
  "helius_api_key": "your-helius-key",
  "wallet_keypair_path": "~/.config/solana/id.json",
  "telegram_bot_token": "your-bot-token",
  "telegram_chat_id": "your-chat-id",
  "max_mint_price_sol": 2.0,
  "require_verified_creator": true
}
```

Environment variables override config file values:
- `SOLANA_RPC_URL` — Solana RPC endpoint
- `HELIUS_API_KEY` — Helius API key for enhanced APIs
- `WALLET_KEYPAIR_PATH` — Path to wallet JSON keypair
- `WALLET_PRIVATE_KEY` — Base58-encoded private key (alternative)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` — Telegram notifications

## Usage

### Scan for New Mints
```bash
python cli.py scan --limit 20 --max-price 1.0
```

### Monitor Candy Machines
```bash
python cli.py monitor --candy-machine CANDY_ID_1 CANDY_ID_2
```

### Mint an NFT
```bash
python cli.py mint CANDY_MACHINE_ID --price 0.5
```

### Full Snipe Mode
```bash
python cli.py snipe --candy-machine CANDY_ID --max-price 2.0
python cli.py snipe --candy-machine CANDY_ID --dry-run  # monitor only
```

### Global Options
```bash
python cli.py --rpc https://your-rpc.com --helius-key KEY --wallet ./keypair.json --log-level DEBUG scan
```

## Architecture

```
cli.py              # CLI entry point with subcommands
config.py           # Settings management (file + env vars)
src/
  scanner.py        # NFT discovery via Helius + Solana RPC
  monitor.py        # WebSocket real-time program monitoring
  mint.py           # Auto-mint via Node.js subprocess
  filters.py        # Candidate filtering + rugcheck heuristics
  notifier.py       # Desktop + Telegram notifications
```

## Disclaimer

This tool is for educational purposes. NFT minting carries financial risk. Always verify smart contracts and collections before minting. The authors are not responsible for any financial losses.
