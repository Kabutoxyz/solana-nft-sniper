"""WebSocket-based real-time monitor for Solana candy machine and NFT programs."""

import asyncio
import json
import logging
import time
from typing import Callable, Optional, List, Dict, Any

import websockets
import httpx

logger = logging.getLogger(__name__)

# Known candy machine program IDs
CANDY_MACHINE_V3 = "Guard1JwRhJkV46PuTs474gwegB3RkqKLi7b7coZQm1m"
CANDY_MACHINE_LEGACY = "cndyAnrLdpjq1SspUz8Bsq3yAgFDiPhT79pJ6Nz1SmL"
METAPLEX_PROGRAM = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"


class ProgramMonitor:
    """Monitor Solana programs via WebSocket for real-time NFT activity."""

    def __init__(self, websocket_url: str, rpc_url: str,
                 on_mint_detected: Optional[Callable] = None,
                 candy_machine_ids: Optional[List[str]] = None):
        self.ws_url = websocket_url
        self.rpc_url = rpc_url
        self.on_mint_detected = on_mint_detected
        self.candy_machine_ids = candy_machine_ids or []
        self._subscriptions: Dict[int, str] = {}
        self._running = False
        self._reconnect_delay = 1.0

    async def start(self) -> None:
        """Start the WebSocket monitor with auto-reconnect."""
        self._running = True
        while self._running:
            try:
                await self._connect_and_listen()
            except websockets.exceptions.ConnectionClosed:
                logger.warning("WebSocket disconnected, reconnecting...")
            except Exception as e:
                logger.error(f"WebSocket error: {e}")

            if self._running:
                logger.info(f"Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)

    async def stop(self) -> None:
        """Stop the monitor."""
        self._running = False
        logger.info("Monitor stopping...")

    async def _connect_and_listen(self) -> None:
        """Establish WebSocket connection and subscribe to programs."""
        logger.info(f"Connecting to {self.ws_url}...")
        async with websockets.connect(self.ws_url, ping_interval=20,
                                       ping_timeout=10) as ws:
            self._reconnect_delay = 1.0
            logger.info("WebSocket connected")

            # Subscribe to candy machine programs
            programs_to_watch = [
                CANDY_MACHINE_V3,
                CANDY_MACHINE_LEGACY,
                METAPLEX_PROGRAM,
            ]
            # Also watch specific candy machine accounts
            for cm_id in self.candy_machine_ids:
                await self._subscribe_account(ws, cm_id)

            for program in programs_to_watch:
                await self._subscribe_program(ws, program)

            # Listen for messages
            async for raw_msg in ws:
                try:
                    msg = json.loads(raw_msg)
                    await self._handle_message(msg)
                except json.JSONDecodeError:
                    logger.debug(f"Non-JSON WebSocket message: {raw_msg[:100]}")
                except Exception as e:
                    logger.error(f"Message handling error: {e}")

    async def _subscribe_program(self, ws, program_id: str) -> None:
        """Subscribe to on-chain program notifications."""
        request = {
            "jsonrpc": "2.0",
            "id": len(self._subscriptions) + 1,
            "method": "programSubscribe",
            "params": [
                program_id,
                {
                    "commitment": "confirmed",
                    "encoding": "jsonParsed",
                    "filters": [],
                },
            ],
        }
        await ws.send(json.dumps(request))
        self._subscriptions[request["id"]] = program_id
        logger.info(f"Subscribed to program: {program_id}")

    async def _subscribe_account(self, ws, account_address: str) -> None:
        """Subscribe to a specific account's changes."""
        request = {
            "jsonrpc": "2.0",
            "id": len(self._subscriptions) + 1000,
            "method": "accountSubscribe",
            "params": [
                account_address,
                {"commitment": "confirmed", "encoding": "jsonParsed"},
            ],
        }
        await ws.send(json.dumps(request))
        self._subscriptions[request["id"]] = account_address
        logger.info(f"Subscribed to account: {account_address}")

    async def _handle_message(self, msg: Dict[str, Any]) -> None:
        """Process incoming WebSocket messages."""
        # Subscription confirmation
        if "result" in msg and "id" in msg:
            sub_id = msg["id"]
            if sub_id in self._subscriptions:
                logger.info(f"Subscription confirmed for {self._subscriptions[sub_id]}: "
                            f"sub_id={msg['result']}")
            return

        # Notification
        method = msg.get("method")
        if method == "programNotification":
            await self._handle_program_notification(msg.get("params", {}))
        elif method == "accountNotification":
            await self._handle_account_notification(msg.get("params", {}))

    async def _handle_program_notification(self, params: Dict[str, Any]) -> None:
        """Handle program change notifications."""
        value = params.get("result", {}).get("value", {})
        account = value.get("pubkey", "")
        data = value.get("account", {})

        logger.info(f"Program notification: account={account}")
        logger.debug(f"Account data: {json.dumps(data)[:500]}")

        # Detect mint activity based on lamport changes / data changes
        lamports = data.get("lamports", 0)
        owner = data.get("owner", "")

        if self.on_mint_detected:
            try:
                result = self.on_mint_detected({
                    "type": "program_change",
                    "account": account,
                    "owner": owner,
                    "lamports": lamports,
                    "data": data,
                    "timestamp": int(time.time()),
                })
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def _handle_account_notification(self, params: Dict[str, Any]) -> None:
        """Handle account-specific change notifications."""
        value = params.get("result", {}).get("value", {})
        data = value.get("account", {})
        logger.info(f"Account change detected: lamports={data.get('lamports', 0)}")

        if self.on_mint_detected:
            try:
                result = self.on_mint_detected({
                    "type": "account_change",
                    "data": data,
                    "timestamp": int(time.time()),
                })
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"Callback error: {e}")

    async def poll_candy_machine(self, candy_machine_id: str,
                                  rpc_url: str) -> Dict[str, Any]:
        """Poll candy machine state via RPC to get mint progress."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Fetch the candy machine account data
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getAccountInfo",
                    "params": [
                        candy_machine_id,
                        {"encoding": "base64"},
                    ],
                }
                resp = await client.post(rpc_url, json=payload)
                if resp.status_code != 200:
                    return {"error": f"RPC error: {resp.status_code}"}

                data = resp.json()
                result = data.get("result", {})
                value = result.get("value")
                if not value:
                    return {"error": "Candy machine account not found"}

                # Parse candy machine data (simplified)
                account_data = value.get("data", [])
                if isinstance(account_data, list) and len(account_data) >= 2:
                    import base64
                    raw = base64.b64decode(account_data[0])
                    # Byte 8-16 typically contains items minted (u64 LE)
                    if len(raw) >= 24:
                        import struct
                        items_minted = struct.unpack_from("<Q", raw, 8)[0]
                        items_available = struct.unpack_from("<Q", raw, 16)[0]
                        return {
                            "candy_machine_id": candy_machine_id,
                            "items_minted": items_minted,
                            "items_available": items_available,
                            "remaining": items_available - items_minted,
                        }

                return {
                    "candy_machine_id": candy_machine_id,
                    "raw_data_length": len(str(account_data)),
                }
        except Exception as e:
            logger.error(f"Candy machine poll error: {e}")
            return {"error": str(e)}
