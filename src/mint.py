"""Auto-mint NFTs using Node.js subprocess with @solana/web3.js."""

import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# JavaScript code for minting an NFT via Candy Machine
MINT_JS_TEMPLATE = """
const {{
    Connection,
    Keypair,
    PublicKey,
    Transaction,
    SystemProgram,
    sendAndConfirmTransaction,
    LAMPORTS_PER_SOL,
    TransactionInstruction,
}} = require("@solana/web3.js");
const bs58 = require("bs58");
const fs = require("fs");

async function mintNFT(config) {{
    const connection = new Connection(config.rpcUrl, "confirmed");

    // Load wallet keypair
    let payer;
    if (config.walletPrivateKey) {{
        payer = Keypair.fromSecretKey(bs58.decode(config.walletPrivateKey));
    }} else {{
        const keyData = JSON.parse(fs.readFileSync(config.walletPath, "utf-8"));
        payer = Keypair.fromSecretKey(Uint8Array.from(keyData));
    }}

    console.log(JSON.stringify({{
        type: "info",
        message: "Wallet loaded",
        pubkey: payer.publicKey.toBase58(),
    }}));

    // Check balance
    const balance = await connection.getBalance(payer.publicKey);
    console.log(JSON.stringify({{
        type: "info",
        message: "Balance",
        sol: balance / LAMPORTS_PER_SOL,
    }}));

    if (balance < config.mintPriceLamports + config.priorityFeeLamports + 5000) {{
        console.log(JSON.stringify({{
            type: "error",
            message: "Insufficient SOL balance",
        }}));
        process.exit(1);
    }}

    // Build the mint transaction
    const mint = Keypair.generate();

    try {{
        // Method: Call candy machine mint instruction
        // The exact instruction depends on Candy Machine version
        // This builds a basic transfer + memo as a framework
        const tx = new Transaction();

        // Add compute budget for priority
        const computeBudgetIx = new TransactionInstruction({{
            programId: new PublicKey("ComputeBudget111111111111111111111111111111"),
            keys: [],
            data: Buffer.from(
                Buffer.from([3])  // SetComputeUnitPrice instruction tag
                    .concat(Buffer.from(config.priorityFeeLamports.toString(16).padStart(16, "0"), "hex"))
            ),
        }});
        tx.add(computeBudgetIx);

        // Candy Machine mint instruction
        // Format: [discriminator (8 bytes)] + [args]
        const candyMachineId = new PublicKey(config.candyMachineId);
        const METADATA_PROGRAM = new PublicKey("metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s");
        const TOKEN_PROGRAM = new PublicKey("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA");

        // Derive PDAs
        const [metadata] = PublicKey.findProgramAddressSync(
            [Buffer.from("metadata"), METADATA_PROGRAM.toBuffer(), mint.publicKey.toBuffer()],
            METADATA_PROGRAM
        );
        const [masterEdition] = PublicKey.findProgramAddressSync(
            [Buffer.from("metadata"), METADATA_PROGRAM.toBuffer(), mint.publicKey.toBuffer(), Buffer.from("edition")],
            METADATA_PROGRAM
        );
        const [tokenAccount] = PublicKey.findProgramAddressSync(
            [payer.publicKey.toBuffer(), TOKEN_PROGRAM.toBuffer(), mint.publicKey.toBuffer()],
            new PublicKey("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
        );

        // For Candy Machine v3 (Guard-based), the mint instruction is:
        // mintV2 with appropriate guard data
        // Here we construct a simplified version

        const TOKEN_METADATA_PROGRAM = METADATA_PROGRAM;

        // Build instruction data: discriminator for "mintV2"
        const discriminator = Buffer.from([51, 57, 225, 53, 181, 68, 123, 153]);
        const args = Buffer.from([0]); // no special args

        const keys = [
            {{ pubkey: candyMachineId, isSigner: false, isWritable: true }},
            {{ pubkey: payer.publicKey, isSigner: true, isWritable: true }},
            {{ pubkey: payer.publicKey, isSigner: false, isWritable: true }},
            {{ pubkey: mint.publicKey, isSigner: true, isWritable: true }},
            {{ pubkey: metadata, isSigner: false, isWritable: true }},
            {{ pubkey: masterEdition, isSigner: false, isWritable: true }},
            {{ pubkey: tokenAccount, isSigner: false, isWritable: true }},
            {{ pubkey: TOKEN_METADATA_PROGRAM, isSigner: false, isWritable: false }},
            {{ pubkey: TOKEN_PROGRAM, isSigner: false, isWritable: false }},
            {{ pubkey: SystemProgram.programId, isSigner: false, isWritable: false }},
        ];

        const mintIx = new TransactionInstruction({{
            programId: candyMachineId,
            keys: keys,
            data: Buffer.concat([discriminator, args]),
        }});
        tx.add(mintIx);

        tx.recentBlockhash = (await connection.getLatestBlockhash()).blockhash;
        tx.feePayer = payer.publicKey;
        tx.partialSign(mint);

        const rawTx = tx.serialize({{ requireAllSignatures: false }});
        const sig = await connection.sendRawTransaction(rawTx, {{
            skipPreflight: false,
            preflightCommitment: "confirmed",
            maxRetries: 3,
        }});

        console.log(JSON.stringify({{
            type: "success",
            signature: sig,
            mintAddress: mint.publicKey.toBase58(),
        }}));

        // Wait for confirmation
        const confirmation = await connection.confirmTransaction(sig, "confirmed");
        console.log(JSON.stringify({{
            type: "confirmed",
            signature: sig,
        }}));

    }} catch (err) {{
        console.log(JSON.stringify({{
            type: "error",
            message: err.message || String(err),
            code: err.code || "UNKNOWN",
        }}));
        process.exit(1);
    }}
}}

const config = JSON.parse(process.argv[2] || "{}");
mintNFT(config).catch(err => {{
    console.log(JSON.stringify({{ type: "error", message: err.message }}));
    process.exit(1);
}});
"""


class NFTMinter:
    """Auto-mint NFTs by spawning a Node.js process with @solana/web3.js."""

    def __init__(self, rpc_url: str, wallet_keypair_path: str = "",
                 wallet_private_key: str = "",
                 max_priority_fee_lamports: int = 100_000,
                 timeout: int = 30, retry_attempts: int = 3,
                 retry_delay: float = 1.0):
        self.rpc_url = rpc_url
        self.wallet_keypair_path = wallet_keypair_path
        self.wallet_private_key = wallet_private_key
        self.max_priority_fee_lamports = max_priority_fee_lamports
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self._js_file: Optional[str] = None

    def _ensure_js_file(self) -> str:
        """Write the minting JS to a temp file if not already done."""
        if self._js_file and os.path.exists(self._js_file):
            return self._js_file
        fd, path = tempfile.mkstemp(suffix=".js", prefix="nft_mint_")
        with os.fdopen(fd, "w") as f:
            f.write(MINT_JS_TEMPLATE)
        self._js_file = path
        return path

    def _check_node_deps(self) -> bool:
        """Verify Node.js and required packages are available."""
        try:
            result = subprocess.run(
                ["node", "-e", "require('@solana/web3.js'); require('bs58');"],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    async def mint(self, candy_machine_id: str,
                   mint_price_lamports: int = 0) -> Dict[str, Any]:
        """Execute NFT mint via Node.js subprocess."""
        import subprocess as sp

        if not self._check_node_deps():
            return {
                "success": False,
                "error": "Node.js dependencies not installed. Run: npm install @solana/web3.js bs58",
            }

        js_path = self._ensure_js_file()
        config = json.dumps({
            "rpcUrl": self.rpc_url,
            "walletPath": self.wallet_keypair_path,
            "walletPrivateKey": self.wallet_private_key,
            "candyMachineId": candy_machine_id,
            "mintPriceLamports": mint_price_lamports,
            "priorityFeeLamports": self.max_priority_fee_lamports,
        })

        for attempt in range(1, self.retry_attempts + 1):
            logger.info(f"Mint attempt {attempt}/{self.retry_attempts} for {candy_machine_id}")
            try:
                proc = await asyncio.create_subprocess_exec(
                    "node", js_path, config,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout
                )

                output = stdout.decode("utf-8").strip()
                err_output = stderr.decode("utf-8").strip()

                if err_output:
                    logger.debug(f"Node stderr: {err_output}")

                # Parse JSON lines from stdout
                result = {"success": False}
                for line in output.split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        if parsed.get("type") == "success":
                            result = {
                                "success": True,
                                "signature": parsed.get("signature"),
                                "mint_address": parsed.get("mintAddress"),
                            }
                        elif parsed.get("type") == "confirmed":
                            result["confirmed"] = True
                        elif parsed.get("type") == "error":
                            result = {
                                "success": False,
                                "error": parsed.get("message", "Unknown error"),
                            }
                        elif parsed.get("type") == "info":
                            logger.info(f"Mint info: {parsed.get('message')}")
                    except json.JSONDecodeError:
                        continue

                if result.get("success"):
                    return result

                # Retry on failure
                if attempt < self.retry_attempts:
                    logger.warning(f"Mint failed, retrying in {self.retry_delay}s: "
                                   f"{result.get('error', 'unknown')}")
                    await asyncio.sleep(self.retry_delay)

            except asyncio.TimeoutError:
                logger.error(f"Mint attempt {attempt} timed out after {self.timeout}s")
                if proc:
                    proc.kill()
            except Exception as e:
                logger.error(f"Mint attempt {attempt} exception: {e}")
                if attempt < self.retry_attempts:
                    await asyncio.sleep(self.retry_delay)

        return {"success": False, "error": "All mint attempts failed"}

    def cleanup(self) -> None:
        """Remove temporary JS file."""
        if self._js_file and os.path.exists(self._js_file):
            try:
                os.unlink(self._js_file)
                self._js_file = None
            except OSError:
                pass

    def __del__(self):
        self.cleanup()
