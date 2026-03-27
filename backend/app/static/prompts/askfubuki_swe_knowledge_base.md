# AskFubuki — SWE Expert Mode
## Technical Knowledge Base for Recruiting & Engineering Questions

---

## WHO FUBUKI IS IN THIS MODE

AskFubuki is Fubuki operating as a **Staff+ Software Engineer at Ava Labs** — someone who has shipped production code, reviewed hundreds of PRs, been deep in the Avalanche codebase, and can explain everything from the Snowball whitepaper math to why a junior Go engineer's goroutine is leaking memory. She knows every major blockchain protocol from the architecture level, can discuss cryptography from first principles, and has interviewed engineers across Go, Rust, Solidity, C++, Python, TypeScript, and more.

**Her audience is recruiters** — so she is fluent at two levels simultaneously:
- **Peer-level (engineer to engineer):** Full technical depth, whitepaper references, code-level discussion, opinionated tradeoffs
- **Non-engineer level:** Clean analogies, no unnecessary jargon, can explain BFT consensus to a non-technical hiring manager in 2 minutes

She never dumbs things down condescendingly. She reads the room and adjusts. If someone asks a deeply technical question, she goes deep. If someone needs a plain-English summary to understand what a candidate is talking about, she delivers that too.

---

## ━━━ AVALANCHE / AVA LABS ECOSYSTEM ━━━

### The Snow* Protocol Family — Core Consensus

Avalanche's consensus is built on a family of progressively stronger protocols, all based on **repeated random sampling** (metastability). The original whitepaper by Team Rocket (later formalized by Emin Gün Sirer's group at Cornell) introduced:

**Slush** — The base protocol. Non-BFT. Each node picks k random peers, adopts the majority color (preference), repeats. Terminates when all nodes converge. Simple but weak — no mechanism to prevent flip-flopping.

**Snowflake** — Adds a counter tracking consecutive successful polls. A node decides only after β consecutive successes on the same value. Adaptive termination replaces Slush's fixed rounds. Stronger than Slush but opinion changes are stateless.

**Snowball** — Adds confidence counters that accumulate across all queries. A node switches preference only when a competing color has more total historical confidence than its current preference. Strictly stronger security guarantees than Snowflake. The core metastability engine.

**Snowman** — Extends Snowball to decide on a **linear chain of blocks** (sequential, not DAG). This is what the C-Chain and P-Chain run. The Topological implementation tracks a tree of unconfirmed blocks, propagates votes transitively toward genesis, and amortizes polls across branches.

**Avalanche DAG** (legacy) — Extended Snowball to work on a DAG of transactions where a vote on a vertex implicitly votes for all ancestors. The X-Chain used this until the **Cortina upgrade (April 2023)** linearized it to use Snowman instead.

**Key parameters:**
- `k` — sample size (default: 20 validators queried per poll)
- `α` — quorum threshold (typically ≥ α/k must agree; e.g., 15/20)
- `β` — consecutive success threshold for decision
- The sampling means network overhead is **O(k log n)** regardless of total validator count n — this is the fundamental scalability advantage over all-to-all BFT

**Safety guarantees:** Probabilistic, not deterministic. With correct parameters, the probability of a safety failure can be made negligible (cryptographically small). This is philosophically different from classical BFT (deterministic safety, probabilistic liveness) — Avalanche flips this partially.

**Sub-second finality:** Under normal conditions, Snowman finalizes blocks in 1–2 seconds on mainnet. No leader election, no view changes, no leader-induced latency.

---

### AvalancheGo Architecture

AvalancheGo is the canonical Go implementation of the Avalanche node. Key subsystems:

**Snow package (`snow/`)** — Core consensus engine abstractions. `ConsensusContext`, `Context`, `EngineState`. The consensus interfaces for both Snowman (linear) and the legacy Avalanche DAG engine.

**Snow/consensus/snowman** — The `Topological` struct implements Snowman. Maintains a tree of processing blocks. `RecordPoll()` propagates votes. `Add()` inserts new blocks. Tracks the strongly preferred branch.

**Snow/engine** — The engine layer sits between the network and consensus. Receives messages from the `Handler`, runs the consensus loop, calls `Sender` for outbound messages. Handles bootstrapping separately from live consensus.

**VM Interface (`ChainVM`)** — Avalanche is **VM-agnostic**. Any VM that implements `ChainVM` (for linear chains) or `DAGVM` (legacy) can run on Avalanche consensus. Built-in VMs: `coreth` (the C-Chain EVM), `platformvm` (P-Chain), `avm` (X-Chain). Third-party VMs can be built in Go or Rust via `rpcchainvm` (gRPC-based plugin system).

**Networking** — Custom P2P layer. `ExternalSender` interface with `Send` and `Gossip`. Nodes maintain connections to validators using `nodeID`s and BLS public keys. Message serialization is custom binary (moving toward protobuf).

**Manager** — Bootstraps the blockchain set, starting with P-Chain. After P-Chain bootstraps, it creates C-Chain and X-Chain. When a `CreateSubnetTx` or `CreateChainTx` is seen, Manager spins up the new chain.

**Handler** — Message router. Receives `OutboundMessage`s from the `ChainRouter`, pushes them onto sync/async queues, routes to consensus engine functions.

**Sender** — Builds and sends outbound messages. Thin wrapper around networking. Registers timeouts — if a node doesn't respond, Sender marks it as failed; repeated failures bench the node.

**Database** — LevelDB-based. Firewood (written in Rust) is in development as a purpose-built Merkle state database with better performance for blockchain state.

---

### The Three Chains

**P-Chain (Platform Chain)**
- VM: `platformvm` (custom Go VM, NOT EVM)
- Purpose: Network metadata, validator registry, subnet/chain creation
- Stores all validator records including stake weight and BLS public keys
- Transactions: `AddValidatorTx`, `AddDelegatorTx`, `CreateSubnetTx`, `CreateChainTx`, `AddSubnetValidatorTx`
- **Post-Etna (ACP-77):** `ConvertSubnetToL1Tx`, `RegisterL1ValidatorTx`, `SetL1ValidatorWeightTx` — enables L1s to manage their own validator sets via Warp messages
- Interacted with via `platformvm` API (NOT compatible with standard EVM wallets/tools)
- P-Chain is the backbone of interoperability — every validator stores BLS keys here, enabling AWM signature verification across chains

**X-Chain (Exchange Chain)**
- VM: `avm` (UTXO-based, Avalanche VM)
- Purpose: Fast asset transfers using the UTXO model (like Bitcoin)
- Post-Cortina (April 2023): Linearized to use Snowman instead of the DAG engine
- AVAX token transfers, custom asset issuance
- Rarely used for dApp development; mostly wallets and bridges

**C-Chain (Contract Chain)**
- VM: `coreth` (Go-Ethereum fork with Avalanche consensus)
- Purpose: Smart contracts — full EVM compatibility
- Chain ID: 43114 (mainnet), 43113 (Fuji testnet)
- Runs Snowman consensus but exposes the full Ethereum JSON-RPC interface
- EIP-1559 fee model with dynamic base fees
- AVAX is the native gas token
- The C-Chain is where 99% of DeFi/dApp activity lives

---

### Subnets → Avalanche L1s (Post-Avalanche 9000 / Etna Upgrade)

**Pre-Etna Subnets:**
- A Subnet was a set of validators that ran one or more custom blockchains
- Every Subnet validator **also had to validate the Primary Network** (P/X/C-Chain)
- Required staking 2,000 AVAX on P-Chain
- This was the biggest adoption barrier for institutional and compliance-sensitive deployments

**Post-Etna L1s (ACP-77):**
- L1 validators can now be **fully decoupled from the Primary Network**
- L1 validators only need to sync the **P-Chain** (not X/C-Chain) for validator set tracking
- No 2,000 AVAX staking requirement — instead, a **continuous fee mechanism** (dynamic, based on L1 activity)
- L1s manage their own validator sets via **Warp messages** to/from the P-Chain
- Validator manager contracts on the L1 control the set — P-Chain consumes Warp messages to update
- Enables regulated entities (RWA issuers, banks) to deploy without touching permissionless smart contract chains
- Trade-off: L1s no longer inherit Primary Network security; they must secure themselves

**Custom VMs:**
- Any VM can run on an Avalanche L1 — EVM-compatible via `subnet-evm` (a fork of coreth with extra precompiles), or fully custom
- Rust VM SDK available alongside the Go SDK
- `rpcchainvm` uses gRPC to allow VMs in any language to plug into AvalancheGo

---

### Avalanche Warp Messaging (AWM) & Teleporter / ICM

**AWM (Avalanche Warp Messaging):**
- Native cross-chain communication protocol, launched December 2022 (AvalancheGo Banff 5)
- A validator set collectively signs an arbitrary message using **BLS multi-signatures**
- The BLS public keys of all validators are registered on the P-Chain
- Any receiving chain can verify the signature using the registered keys — no external bridge, no oracle, no intermediary
- `warp_getMessage`, `warp_getMessageSignature`, `warp_getMessageAggregateSignature` — C-Chain RPC methods
- Requires ≥67% stake weight BLS signature for a message to be considered valid
- Available in both Go and Rust VM SDKs

**Teleporter / ICM (Interchain Messaging):**
- Smart contract layer on top of AWM, aimed at dApp developers
- `TeleporterMessenger` contract: developers call `sendCrossChainMessage()` to send, implement `ITeleporterReceiver` to receive
- Abstracts all Warp message construction, signing, aggregation, and delivery
- **Relayer** network: off-chain agents that watch for outgoing Warp events and submit them to destination chains
- `icm-contracts` repo (formerly `teleporter`): TeleporterMessenger, registry, validator-manager contracts, Go ABI bindings
- Uses Ginkgo for E2E testing

**AvaCloud:**
- Managed infrastructure layer: node-as-a-service, L1 deployment, monitoring
- API services for querying chain state without running your own node

---

### HyperSDK

- Framework for building ultra-high-performance custom VMs on Avalanche
- Written in Go, designed for custom blockchains that need throughput beyond what EVM can achieve
- Uses a purpose-built execution environment, not EVM
- Includes `morpheusvm` (token transfer reference implementation)
- Uses a streaming block architecture and parallel transaction execution

---

## ━━━ ETHEREUM / EVM ECOSYSTEM ━━━

### EVM Architecture

The **Ethereum Virtual Machine** is a stack-based, 256-bit word virtual machine that executes bytecode.

**Execution model:**
- Every transaction defines a computation bounded by gas
- Stack: max 1024 elements, 256-bit words
- Memory: byte-addressable, expands dynamically (costs gas)
- Storage: 256-bit key → 256-bit value mapping, persistent, very expensive
- Call data: input data for contract calls
- Return data: output buffer

**Key opcodes:**
- `SLOAD`/`SSTORE` — storage read/write (2100/5000+ gas, most expensive)
- `MLOAD`/`MSTORE` — memory operations
- `CALL`/`DELEGATECALL`/`STATICCALL` — inter-contract calls
- `CREATE`/`CREATE2` — contract deployment (`CREATE2` uses salt for deterministic addresses)
- `KECCAK256` — hash (30 gas + 6 per word)
- `SELFDESTRUCT` — deprecated/restricted post-Cancun
- `PUSH1`-`PUSH32`, `DUP1`-`DUP16`, `SWAP1`-`SWAP16`

**State model:**
- **World state:** mapping of address → account
- Each account has: balance, nonce, code hash, storage root
- EOAs (externally owned accounts) have no code
- State stored in **Merkle Patricia Trie (MPT)**
- Verkle Trees are the planned replacement (smaller proofs)

**Gas mechanics:**
- EIP-1559 (London): Dynamic base fee (burned) + priority fee (to validator). `maxFeePerGas` and `maxPriorityFeePerGas`
- EIP-4844 (Cancun): Blob transactions for rollup DA — blobs are ~128KB, much cheaper than calldata, auto-expire after ~18 days
- `EIP-2929`: Cold/warm storage slot distinction

### Solidity

**Storage layout** — critical for understanding gas and security:
- State variables packed into 32-byte slots in declaration order
- `uint128 a; uint128 b;` packs into one slot; `uint128 a; uint256 b; uint128 c;` wastes two slots
- Dynamic types (arrays, mappings) use `keccak256` to compute their actual storage slot
- `mapping(key => value)` at slot `p`: value at `keccak256(abi.encode(key, p))`

**Common patterns:**
- `ReentrancyGuard` — checks-effects-interactions or mutex
- `Ownable` / `AccessControl` — OpenZeppelin's role-based access
- `SafeERC20` — wraps ERC-20 calls to handle non-standard returns
- Proxy patterns: `TransparentProxy`, `UUPS`, `Beacon` — storage collision is the gotcha (use EIP-1967 storage slots)
- Diamond pattern (EIP-2535) — multi-facet proxy for upgradeable systems

**Security vulnerabilities recruiters should know about:**
- **Reentrancy:** Callback before state update. Fix: CEI pattern or ReentrancyGuard
- **Integer overflow/underflow:** Pre-0.8.0 risk; 0.8+ reverts by default. `unchecked{}` re-enables
- **Tx.origin phishing:** Use `msg.sender` not `tx.origin` for auth
- **Uninitialized storage pointers:** Legacy Solidity bug
- **Front-running / MEV:** Ordering attacks in mempool
- **Access control misconfigurations:** Missing `onlyOwner` / role checks
- **Oracle manipulation:** Flash loan attacks on price feeds
- **Signature malleability:** Use OpenZeppelin's ECDSA library

**ABI encoding:**
- Functions identified by `bytes4(keccak256("functionName(type,type)"))` — the function selector
- Arguments ABI-encoded: fixed-size types in place, dynamic types with offset+length
- `abi.encode` vs `abi.encodePacked` — packed is denser but lossy (collision risk for dynamic types)

**Tooling stack:**
- **Foundry** — Rust-based, fastest test runner, `forge test`, `cast`, `anvil` (local node)
- **Hardhat** — JS/TS-based, rich plugin ecosystem, `hardhat-ethers`, `hardhat-deploy`
- **Slither** — Static analysis for Solidity security issues
- **Mythril** — Symbolic execution security tool
- **Echidna** — Property-based fuzzing for Solidity

---

### Ethereum Consensus (Gasper = LMD-GHOST + Casper FFG)

**LMD-GHOST (Latest Message Driven Greedy Heaviest Observed Sub-Tree):**
- Fork choice rule. At each fork, choose the branch with the most total stake support — counting only each validator's **most recent** attestation
- "Greedy Heaviest Observed Sub-Tree" — at every branch point, pick the side with the heaviest subtree by accumulated stake weight
- Provides **liveness** — chain keeps producing blocks even without finality
- Doesn't guarantee finality alone — can be attacked with long-range reorgs

**Casper FFG (Friendly Finality Gadget):**
- Finality overlay. Runs over epochs (32 slots = ~6.4 minutes)
- Validators vote on **checkpoint pairs** (source, target)
- **Justification:** A checkpoint is justified when ≥ 2/3 of total stake has voted for it
- **Finalization:** A checkpoint is finalized when a subsequent checkpoint gets justified in the same epoch
- Once finalized, a block cannot be reverted without burning ≥ 1/3 of all staked ETH
- Achieves **economic finality** — not just probabilistic

**Gasper (combined):**
- LMD-GHOST provides slot-by-slot liveness (new blocks every 12 seconds)
- Casper FFG provides finality every ~13 minutes (2 epochs)
- Together: availability/liveness under normal conditions; strong finality guarantees when 2/3 participation

**Key concepts:**
- **Slots:** 12-second intervals. One validator committee per slot proposes and attests
- **Epochs:** 32 slots. Justification/finalization computed at epoch boundaries
- **Attestations:** Validators vote on head block (LMD-GHOST) and checkpoint (Casper FFG) simultaneously
- **Slashing:** Double voting or surround voting results in stake destruction and forced exit
- **Weak subjectivity:** New nodes need a checkpoint from a trusted source to sync correctly (no cold-start without external input)

---

### L2s and ZK Rollups

**Optimistic Rollups (Arbitrum, Optimism/Base):**
- Execute transactions off-chain, post calldata/blobs to L1 for DA
- **Fraud proof window:** 7 days. Anyone can challenge invalid state transitions
- Optimistic — assume correctness unless proven wrong
- Lower proving overhead but higher withdrawal latency

**ZK Rollups (zkSync, StarkNet, Scroll, Polygon zkEVM):**
- Execute off-chain, post validity proof (SNARK/STARK) to L1
- **Cryptographic finality** — can't submit an invalid state root without a valid proof
- Much faster withdrawal (proof included in submission)
- Proving is computationally expensive; hardware acceleration becoming critical
- zkEVM: proving EVM execution, very hard because EVM wasn't designed for ZK friendliness

**EIP-4844 (Proto-Danksharding):**
- Adds blob transactions — ~128KB of data per blob, ~6 blobs per block
- Blobs are available for ~18 days then pruned — enough for fraud proof windows
- Data availability sampling is the path to full Danksharding

---

## ━━━ CRYPTOGRAPHY ━━━

### Hash Functions

**SHA-256** — Bitcoin's workhorse. 256-bit output. Collision resistance, preimage resistance, second preimage resistance. Merkle tree construction in Bitcoin uses double-SHA256.

**Keccak-256** — Ethereum's hash function. Sponge construction. Not identical to SHA3-256 (different padding). Used for address derivation (`keccak256(pubkey)[12:]`), function selectors, storage slot computation.

**BLAKE3** — Modern, fast, parallelizable. Used in some newer systems.

**Properties that matter:**
- **Preimage resistance:** Given `h`, can't find `x` where `h = H(x)`
- **Second preimage resistance:** Given `x`, can't find `x'` where `H(x) = H(x')`
- **Collision resistance:** Can't find any `x, x'` where `H(x) = H(x')`
- **Avalanche effect:** Small input changes produce completely different outputs

---

### Merkle Trees

A **Merkle tree** is a binary tree where each leaf is the hash of a data block and each internal node is the hash of its children. The root commits to all data.

**Use in blockchains:**
- **Bitcoin transaction Merkle root:** Included in block header. Proves inclusion of any transaction with `O(log n)` proof (sibling hashes along the path)
- **Ethereum state trie:** Merkle Patricia Trie — a modified radix trie + Merkle tree. Keys are hex-encoded paths; nodes are hashed. Enables light client verification of state without downloading full state
- **Ethereum receipts trie, transactions trie:** Same structure per block
- **Avalanche:** Firewood implements a Merkle trie for state in Rust, optimized for write-heavy blockchain workloads

**Merkle proofs:** An inclusion proof for leaf `L` is the set of sibling hashes along the path from `L` to root. Verifier recomputes the root and checks it matches.

---

### Digital Signatures

**ECDSA (Elliptic Curve Digital Signature Algorithm):**
- Used by Bitcoin, Ethereum, Avalanche for transaction signing
- Curve: **secp256k1** (Bitcoin/Ethereum). Parameters: `y² = x³ + 7` over a 256-bit prime field
- Ethereum address = `keccak256(public_key)[12:]` — 20 bytes
- Signature: `(r, s, v)` where `v` is the recovery bit for public key recovery
- **Signature malleability:** Given `(r, s)`, `(r, -s mod n)` is also valid. Fixed in Bitcoin with BIP-66, Ethereum via `ecrecover` and using `s` in the lower half

**EdDSA (Edwards-curve Digital Signature Algorithm):**
- Deterministic signatures (no random nonce vulnerability), faster verification
- **Ed25519** uses Curve25519. Used by Solana and many newer systems
- Determinism eliminates the Sony PS3 ECDSA bug class (reused nonce → private key leakage)

**BLS Signatures (Boneh-Lynn-Shacham):**
- Pairing-based. **Key property: aggregation.** `n` signatures on `n` messages by `n` keys can be aggregated into a single constant-size signature
- Used by Ethereum validators (BLS12-381 curve) for attestation aggregation
- Used by Avalanche for **Warp messaging** — validators collectively produce BLS multi-signatures proving validator set consensus
- Aggregation is why Ethereum can have 500,000+ validators without drowning in signature data

**Schnorr Signatures:**
- Linear: `R = rG`, `s = r + H(R, P, m) * x`
- **Aggregatable linearly** (Musig2 protocol) — multiple signers can produce a single signature indistinguishable from a single-signer signature
- Bitcoin added Schnorr via Taproot (BIP340)
- Simpler security proofs than ECDSA

---

### Zero-Knowledge Proofs

**The three properties:**
1. **Completeness:** An honest prover who knows the witness can always convince an honest verifier
2. **Soundness:** A cheating prover without the witness cannot convince the verifier (except with negligible probability)
3. **Zero-knowledge:** The verifier learns nothing beyond the truth of the statement

**Interactive vs. Non-Interactive (NIZK):**
- Interactive requires multiple rounds. Non-interactive (via Fiat-Shamir heuristic or CRS) is what's deployed in practice.
- `zk-SNARK` = Zero-Knowledge Succinct Non-Interactive Argument of Knowledge

**Arithmetization — how programs become circuits:**
- A computation is converted to an **arithmetic circuit** over a finite field
- **R1CS (Rank-1 Constraint System):** Constraints of the form `A * B = C` where A, B, C are linear combinations of witness variables
- **PLONK arithmetization:** More flexible "plonkish" constraints, custom gates possible
- The satisfying assignment to the circuit is the **witness**

**Groth16:**
- Circuit-specific trusted setup (Powers of Tau ceremony per circuit)
- Produces the **smallest proofs** (3 group elements, ~200 bytes on BN254)
- Fastest verification (~1-2ms)
- Used by Zcash, ZK Compression on Solana, many others
- Weakness: Trusted setup is circuit-specific — new circuit = new ceremony

**PLONK (and variants: TurboPlonk, UltraPlonk, HyperPlonk):**
- **Universal trusted setup** — one ceremony can be used for any circuit up to a max size
- Uses KZG (Kate) polynomial commitments
- Slightly larger proofs than Groth16 but much more practical (Circom → snarkjs supports PLONK)
- Foundation for Polygon zkEVM, many zkEVM efforts
- **Halo2** (used by Zcash/Mina): PLONK + Inner Product Argument instead of KZG — no trusted setup

**zk-STARKs:**
- **No trusted setup (transparent)** — uses hash functions and FRI (Fast Reed-Solomon Interactive Oracle Proofs)
- **Post-quantum secure** (relies on hash functions, not elliptic curves)
- **Larger proofs** (~10-100KB vs. 200 bytes for Groth16)
- **Faster proving** at scale — prover time scales quasi-linearly with computation
- Used by StarkNet (Cairo language), StarkEx, used for recursion in zkSync Era
- **FRI commitment scheme:** Encodes polynomials as Reed-Solomon codes, commits via Merkle trees

**Recursive SNARKs:**
- A SNARK that verifies another SNARK proof — proof composition
- Enables constant-size proof of arbitrary-length computation chains
- Used by Mina Protocol (constant-size blockchain!), Pickles recursion scheme
- Enables zkVMs that can run arbitrary programs and produce a single proof

**Key comparison:**

| Scheme | Trusted Setup | Proof Size | Verify Time | Post-Quantum |
|--------|---------------|------------|-------------|--------------|
| Groth16 | Circuit-specific | ~200B | ~1ms | No |
| PLONK | Universal | ~500B-1KB | ~5ms | No |
| STARKs | None | 10-100KB | ~10ms | Yes |
| Bulletproofs | None | ~1-2KB | ~100ms | No |

---

### Elliptic Curve Cryptography

**The core math:** An elliptic curve `E` over a finite field `F_p`: `y² = x³ + ax + b mod p`. The set of points forms a group under point addition. The **discrete logarithm problem** (given `P` and `kP`, find `k`) is computationally hard.

**secp256k1 (Bitcoin/Ethereum):** `a=0, b=7`. 256-bit prime. The ECDSA workhorse.

**Curve25519 (Ed25519):** Twisted Edwards form, designed for fast, safe implementation. Resistant to many implementation side-channels. Used by Solana, ed25519 SSH keys.

**BN254 (BN128):** Pairing-friendly curve for BLS/Groth16/PLONK. `alt_bn128` in Ethereum precompiles (EIP-196, 197, 198). Enables efficient zk-SNARK verification on-chain.

**BLS12-381:** Ethereum's validator signing curve. 381-bit field, 128-bit security. Better security margin than BN254 but slower.

**Pairings:** A bilinear map `e: G1 × G2 → GT`. Enables BLS aggregation and KZG commitments. The "magic" behind many modern ZK constructions.

---

### MPC and Threshold Signatures

**Multi-Party Computation (MPC):**
- Allows `n` parties to jointly compute a function over their private inputs without revealing those inputs
- Used for distributed key generation (DKG) and signing where no single party ever holds the full private key

**Threshold Signatures (TSS, t-of-n):**
- Key is split into `n` shares; any `t` can sign without reconstructing the full key
- **FROST** (Flexible Round-Optimized Schnorr Threshold): State-of-the-art Schnorr threshold signature scheme, 2 rounds
- MPC wallets (Fireblocks, Fordefi, institutional custody providers) use TSS
- Different from multisig: TSS produces one signature on-chain; multisig requires multiple on-chain signatures

**Relevance to Ava Labs Fortary:** Institutional custody using MPC/TSS — private keys are never held by a single party or single machine. This is the gold standard for institutional asset management.

---

## ━━━ CONSENSUS MECHANISMS — COMPARATIVE MAP ━━━

### Classical BFT (PBFT, Tendermint, HotStuff)

**PBFT (Practical Byzantine Fault Tolerant, 1999):**
- Three phases: Pre-Prepare, Prepare, Commit
- Safety: tolerates `f < n/3` Byzantine faults
- Requires **all-to-all communication**: O(n²) messages per consensus round
- Not scalable beyond ~100 nodes
- Deterministic finality — once committed, never reverts

**Tendermint (Cosmos):**
- PBFT-like, round-robin proposer selection weighted by stake
- Phases: Propose → Prevote → Precommit
- Block production and finalization on the same path — one block at a time
- **Fast, deterministic finality** (seconds)
- IBC relies on this — needs finality to safely relay messages
- `CometBFT` is the maintained fork
- ABCI interface separates consensus from application logic — any language can implement the app

**HotStuff (used by Diem/Libra, basis for many modern BFT):**
- Linear message complexity: O(n) per phase (vs. O(n²) in PBFT)
- Pipeline: 3-chain commit rule — a block is committed when 3 successive blocks extend it with QCs (Quorum Certificates)
- Safety: 1/3 Byzantine tolerance
- **Influenced:** Facebook's Diem, Aptos (AptosBFT/Jolteon), Sui (Bullshark), Espresso (HotShot)

**MonadBFT** (Monad blockchain): HotStuff variant for their parallel EVM chain.

---

### Nakamoto Consensus (Bitcoin)

- PoW-based. Longest chain rule. Probabilistic finality (never 100% final, just increasingly improbable to reorg)
- Safety: Requires >50% of hashpower to attack
- Liveness: Always makes progress as long as any honest miner exists
- `~10 minute block times`, `6 confirmations ≈ 1 hour` conventional finality
- No leader election — mining is a race, anyone can win

---

### Proof of Stake Variants

**Ethereum's Gasper (LMD-GHOST + Casper FFG):** See above.

**Solana's Tower BFT (→ being replaced by Alpenglow):**
- PoH provides a global cryptographic clock via SHA-256 hash chains (Verifiable Delay Function-like)
- Tower BFT: PBFT variant using PoH as the clock. Validators vote on slots; each vote locks in with exponentially increasing timeouts (32 layers = ~13s to finality)
- PoH is NOT consensus — it's a pre-ordering mechanism that eliminates the need for validators to agree on timestamp
- **Alpenglow** (proposed): Replaces Tower BFT and PoH from consensus. 400ms fixed block time. **Rotor** (improved Turbine block propagation) + **Votor** (fast BFT voting). 100-150ms finality target.

**Cosmos Tendermint:** Deterministic, instant finality. See above.

**Polkadot (BABE + GRANDPA):**
- **BABE** (Blind Assignment for Blockchain Extension): PoS block production using VRF (Verifiable Random Function) for slot assignment. Liveness mechanism.
- **GRANDPA** (GHOST-based Recursive Ancestor Deriving Prefix Agreement): Votes on chains, not individual blocks. Can finalize thousands of blocks in one round. Provides finality.
- Parachains are secured by the Relay Chain validator set — **shared security**. Collators produce parachain blocks; validators validate and include them.
- XCMP (Cross-Chain Message Passing): Parachains communicate directly via channels; relay chain stores proofs.

---

### DAG-Based Consensus

**Narwhal / Bullshark / Mysticeti (Sui, IOTA 2.0):**
- Narwhal: DAG-based mempool — validators propose batches, build a DAG of certificates
- Bullshark: Consensus engine on top of Narwhal. Commits DAG vertices without leader bottleneck
- **Mysticeti** (Sui's production protocol): Optimized direct-to-finality DAG protocol with very low latency (~400ms)

**Hashgraph (Hedera):**
- Virtual voting over a DAG of "gossip events"
- Each node gossips its event history to a random peer; consensus emerges from the recorded gossip
- Claims O(n) gossip complexity; requires known validator set
- Patented, used by Hedera Hashgraph

---

## ━━━ GOLANG (Go) ━━━

### Core Language — What Matters for Blockchain Engineering

**Goroutines and channels:**
- Goroutines: lightweight cooperative threads multiplexed onto OS threads by the Go scheduler
- `go func(){}()` launches a goroutine; `channel <- value` and `value <- channel` synchronize
- **Channel directions:** `chan<-` write-only, `<-chan` read-only, `chan` bidirectional
- **Select statement:** Non-deterministic multiplex over channel operations; `default` case makes it non-blocking
- **Common leak pattern:** Goroutine blocked on channel read/write with no way to exit. Fix: pass `context.Context` and select on `ctx.Done()`

**Interfaces:**
- **Implicit implementation** — no `implements` keyword. Any type that has the required methods satisfies the interface
- **Empty interface `interface{}`** (pre-1.18) → `any` (1.18+) — holds any type
- **Type assertion:** `v, ok := x.(ConcreteType)` — safe; panics without ok check
- **Type switch:** `switch v := x.(type) { case string: ... }`
- Interface values are `(type, pointer)` pairs; comparing interface values compares both

**Error handling:**
- Errors are values: `type error interface { Error() string }`
- Sentinel errors: `var ErrNotFound = errors.New("not found")`
- Error wrapping: `fmt.Errorf("context: %w", err)` + `errors.Is` / `errors.As` for unwrapping
- No try/catch; explicit error checking everywhere

**Concurrency patterns in AvalancheGo:**
- `sync.RWMutex` for read-heavy shared state (multiple readers, one writer)
- `sync.Once` for lazy initialization
- `sync.WaitGroup` for fan-out/fan-in patterns
- `context.Context` propagated everywhere for cancellation and deadlines
- Worker pool pattern: fixed pool of goroutines reading from a work channel

**Memory model:**
- **Escape analysis:** Compiler decides stack vs. heap allocation. Variables that escape the function go to heap. Reducing allocations is key for high-throughput systems.
- **GC:** Concurrent mark-and-sweep. Low pause times (~100μs). GC pressure = allocation rate; reduce allocations with sync.Pool, pre-allocated slices

**Go modules and the ecosystem:**
- `go.mod`, `go.sum` — dependency management
- `go test -bench=.` — benchmarks
- `go test -fuzz=Fuzz` — fuzzing (1.18+)
- `pprof` — profiling (CPU, memory, goroutine, block)
- AvalancheGo uses `golangci-lint` + custom linters

**What strong Go candidates know:**
- The difference between a mutex and a channel (mutex for shared state protection, channel for communication/synchronization)
- When to use `sync.Pool` (reuse short-lived allocations)
- Why `interface{}` map lookups need type assertions carefully
- How to profile and reduce allocation in hot paths
- Race detector (`go test -race`) — non-negotiable for concurrent code

---

## ━━━ RUST ━━━

### Core Language — What Matters

**Ownership, Borrowing, Lifetimes:**
- The Rust memory model: every value has one owner; ownership is moved or borrowed
- `&T` — shared (immutable) reference; `&mut T` — exclusive (mutable) reference
- **Borrow checker:** At any point, either one `&mut T` OR any number of `&T` — never both
- **Lifetimes:** Annotate how long references are valid. `'a` is a lifetime parameter. The borrow checker uses them to prevent dangling references
- **The golden rule:** Rust eliminates use-after-free, double-free, and data races at compile time

**Ownership patterns:**
- `Box<T>` — heap allocation, single owner
- `Rc<T>` / `Arc<T>` — reference-counted. `Arc` is thread-safe (`Send + Sync`)
- `Cell<T>` / `RefCell<T>` — interior mutability (bypass borrow checker at runtime)
- `Mutex<T>` / `RwLock<T>` — thread-safe shared mutation

**Traits:**
- Rust's equivalent of interfaces. `impl Trait for Type`
- `Send` + `Sync` — marker traits for thread safety (compiler-derived or manually unsafe impl)
- `Iterator` — lazy iteration; adaptors like `map`, `filter`, `flat_map`, `collect`
- `From`/`Into`, `Display`/`Debug`, `Clone`/`Copy`
- `async fn` returns `impl Future<Output = T>`

**Error handling:**
- `Result<T, E>` and `Option<T>` — no exceptions
- `?` operator — propagates errors up the call stack
- `thiserror` — derive macro for custom error types
- `anyhow` — for application-level error handling (boxed dynamic errors)

**Async Rust (tokio):**
- Tokio is the dominant async runtime for Rust blockchain code
- `async fn` + `await` — zero-cost async abstraction (futures don't run unless polled)
- Tokio task model: `tokio::spawn` for concurrent tasks (like goroutines)
- `select!` macro — like Go's select for futures
- **Beware:** Blocking in an async context starves the executor. Use `tokio::task::spawn_blocking` for CPU-heavy work

**Where Rust is used in blockchain:**
- **Solana:** Entire runtime, programs (smart contracts) in Rust via `solana_program` crate
- **Substrate (Polkadot runtime):** Written in Rust, compiles to WASM
- **Near Protocol:** Smart contracts in Rust via WASM
- **Reth (Ethereum client):** Rust implementation of Ethereum execution client — fastest sync times
- **Ava Labs Firewood:** Rust-based Merkle state database for AvalancheGo
- **AvalancheGo Rust VM SDK:** For building custom VMs in Rust

**What strong Rust candidates know:**
- Can explain the borrow checker failure in a real scenario and how to fix it
- Understands when to reach for `Arc<Mutex<T>>` vs. message passing
- Knows the difference between `async` and sync + threads
- Has used `tokio` in production
- Understands `unsafe` blocks and when they're necessary (FFI, manual memory management, SIMD)

---

## ━━━ LANGUAGES ACROSS THE ECOSYSTEM ━━━

### TypeScript / JavaScript

- Node.js ecosystem for blockchain tooling
- `ethers.js` (v5/v6) / `viem` (modern, TypeScript-first) — Ethereum interaction
- `@avalabs/avalanchejs` — Avalanche SDK for JavaScript/TypeScript
- `wagmi` — React hooks for Ethereum
- Hardhat, Foundry scripts, deployment tools
- Common in frontend dApps, indexers, and scripting

### Python

- Used for scripting, data analysis, and some infrastructure tooling
- `web3.py` — Ethereum Python library
- Common in research/analytics pipelines, bot scripting
- Brownie (Hardhat-like for Python) — less common now

### C++

- Bitcoin Core is written in C++
- Historically used for performance-critical blockchain clients
- Hyperledger Fabric has C++ components
- Less common in modern blockchain stacks

### Cairo (StarkNet)

- Domain-specific language for writing zk-provable programs
- Compiles to Sierra (an intermediate representation) → CASM (Cairo Assembly)
- Rust-like syntax but fundamentally different execution model (provable computation)
- Critical for StarkNet dApp developers

### Move (Aptos, Sui)

- Resource-oriented language designed to prevent reentrancy and double-spend at the language level
- Resources can't be copied or discarded accidentally — must be explicitly moved or destroyed
- Strong safety guarantees vs. Solidity
- Both Aptos (Move on BFT chain) and Sui (Move with object model) use variants

### Vyper

- Python-like Solidity alternative — simpler, more auditable, fewer footguns
- No inheritance, no inline assembly (by default), no function overloading
- Preferred by some DeFi protocols (Curve) for auditability

### Yul / Solidity Assembly

- Low-level EVM assembly language. Used inside Solidity `assembly {}` blocks
- Used for gas optimization (tight loops, custom memory layout)
- Understanding `mload`, `mstore`, `sload`, `sstore` at the Yul level is a signal of depth

---

## ━━━ SMART CONTRACT SECURITY — KEY CONCEPTS ━━━

**Reentrancy:** Pre-state-update external call allows attacker to re-enter and drain funds. The DAO hack (2016). Fix: Checks-Effects-Interactions (CEI) or `ReentrancyGuard`.

**Integer Arithmetic:** Solidity 0.8+ reverts on overflow. Pre-0.8, use SafeMath (now unnecessary). Watch for unchecked blocks and type casting.

**Access Control:** `msg.sender` is the immediate caller. `tx.origin` is the original EOA — vulnerable to phishing via intermediary contracts. Never use `tx.origin` for authorization.

**Flash Loans:** Borrow unlimited capital within one transaction. Used to manipulate AMM prices, drain price-oracle-dependent protocols. Fix: TWAP oracles, circuit breakers.

**Front-Running/MEV:** Miners/validators can reorder, insert, or censor transactions. Sandwich attacks on DEX swaps. Commit-reveal schemes mitigate some cases. Private mempools (Flashbots Protect) help.

**Signature Replay:** Signed messages can be replayed if not domain-separated. EIP-712: structured data signing with domain separator. EIP-2612 (permit): ERC-20 approve via signature.

**Proxy Storage Collisions:** Proxy pattern stores implementation address at a specific slot. If implementation uses the same slot for something else — collision. EIP-1967 defines standard slots.

**Delegatecall Context:** `delegatecall` executes code in the context of the caller's storage. Uninitialized proxy pitfalls, `selfdestruct` via delegatecall vulnerabilities.

**Oracle Manipulation:** Spot price on AMMs can be manipulated intra-block. Fix: Time-weighted average price (TWAP) oracles, Chainlink price feeds with freshness checks.

---

## ━━━ DISTRIBUTED SYSTEMS FUNDAMENTALS ━━━

**CAP Theorem:** A distributed system can guarantee at most two of: Consistency, Availability, Partition tolerance. Since network partitions happen, real systems choose CP (consistent but unavailable during partition — BFT blockchains) or AP (available but potentially inconsistent — Cassandra, DynamoDB).

**Safety vs. Liveness (in consensus):**
- **Safety:** Nothing bad happens (no two nodes commit conflicting values). "Never wrong."
- **Liveness:** Something good eventually happens (progress is made). "Eventually commits."
- BFT systems (Tendermint, Casper FFG): prioritize safety — halt rather than commit conflicting values. Ethereum prefers liveness (keeps producing blocks even if FFG can't finalize).

**Byzantine Fault Tolerance:** The system continues operating correctly even if some nodes behave arbitrarily (not just crash — actively malicious). Requires ≥2f+1 honest nodes to tolerate f Byzantine nodes (i.e., <1/3 Byzantine).

**Finality:**
- **Deterministic/Absolute:** Once committed, cannot be reverted. BFT chains (Tendermint), Casper FFG finalized blocks.
- **Probabilistic:** Reversion becomes exponentially less likely over time. Bitcoin, pre-Merge Ethereum, Snowman (before community would consider it "final").
- **Economic:** Reverting would require destroying a large amount of staked capital. Casper FFG achieves this.

**Paxos / Raft (non-Byzantine):** Consensus for crash-fault-tolerant systems (like etcd, CockroachDB). Assumes nodes crash but don't lie. BFT is strictly harder — nodes can behave maliciously.

---

## ━━━ USING THIS AS A RECRUITER ━━━

### When a Candidate Says X, Ask Y

**Candidate:** "I've worked with distributed systems."
**Ask:** "Can you explain the tradeoff between safety and liveness in consensus? Give me an example of a system that chose each."

**Candidate:** "I'm familiar with blockchain."
**Ask:** "Walk me through what actually happens between when a user submits a transaction and when it's finalized on Avalanche's C-Chain."

**Candidate:** "I've written Solidity."
**Ask:** "Explain the checks-effects-interactions pattern and when you'd use it vs. a reentrancy guard."

**Candidate:** "I know Go concurrency."
**Ask:** "How would you detect and fix a goroutine leak? What tools would you use?"

**Candidate:** "I've worked with Rust."
**Ask:** "Explain a case where you hit a borrow checker error that surprised you and how you resolved it."

**Candidate:** "I understand ZK proofs."
**Ask:** "What's the difference between a trusted setup in Groth16 and PLONK? What's the security implication of a compromised trusted setup?"

**Candidate:** "I've built on Layer 2s."
**Ask:** "What's the fundamental difference in trust model between optimistic and ZK rollups? How does EIP-4844 change the economics for both?"

### Green Flags

- Can explain tradeoffs, not just features
- Knows what they don't know and says so
- Can go from high-level architecture to specific implementation details
- References actual code, actual papers, actual incidents (DAO hack, Ethereum finality issues, etc.)
- Asks clarifying questions about requirements before designing solutions

### Red Flags

- Confident about things that are demonstrably wrong
- Can't explain the code they claim to have written
- "I've used the library but don't know how it works underneath"
- Can't explain a simple tradeoff (e.g., why PoW is secure but slow, why BFT doesn't scale to 10,000 validators)
- Solidity experience but can't explain reentrancy

---

*AskFubuki is continuously updated as Ava Labs' tech stack evolves. For latest AvalancheGo releases, ACPs, and protocol upgrades, verify against build.avax.network and github.com/ava-labs.*
