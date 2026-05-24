# Solana NFT Sniper

Automated NFT sniping bot for Solana blockchain with Magic Eden integration.

## Features
- Real-time floor price monitoring
- Auto-buy on price drops
- Rarity analysis
- Profit tracking

## Installation

```bash
# Clone repository
git clone https://github.com/Kabutoxyz/solana-nft-sniper.git
cd solana-nft-sniper

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your wallet private key and RPC endpoint
```

## Usage

```python
from sniper import NFTSniper

# Initialize sniper
sniper = NFTSniper(
    wallet_private_key="your_private_key",
    rpc_endpoint="https://api.mainnet-beta.solana.com"
)

# Monitor collection
sniper.monitor_collection(
    collection_id="degods",
    max_price=50,  # SOL
    auto_buy=True
)
```

## Configuration

Create `.env` file:
```
WALLET_PRIVATE_KEY=your_solana_private_key
RPC_ENDPOINT=https://api.mainnet-beta.solana.com
MAGIC_EDEN_API_KEY=your_api_key
```

## Tech Stack
- Python 3.11+
- Solana Web3.py
- Magic Eden API

## Roadmap
- [x] Basic monitoring
- [ ] Rarity scoring
- [ ] Multi-collection support
- [ ] Telegram alerts

## Disclaimer
Use at your own risk. This is for educational purposes only.

## License
MIT License - see LICENSE file


## Usage

```bash
# Run the script
python main.py

# With custom parameter (if supported)
python main.py <parameter>
```

## Example Output

```
🔍 Running...
⏰ 2026-05-24 11:00:26
✅ Data fetched successfully
```

## Notes

- Uses public APIs (no API key required)
- Rate limits apply
- For educational purposes
