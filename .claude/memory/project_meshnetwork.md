---
name: MeshNetwork project state
description: IoT LoRa mesh PoC — hardware, protocol design, adaptive SF goal, current implementation status
type: project
---

COMP 4531 IoT project implementing adaptive-SF LoRa mesh on XIAO boards.

**Hardware:** 5× XIAO ESP32-S3 + SX1262, 1× XIAO nRF52840 + SX1262 (BLE gateway). CircuitPython.
**Parameters:** 912 MHz, BW 125 kHz, CR 4/5, 22 dBm TX (ESP32), SX1262 sx1262 library.

**Goal:** Prove per-link adaptive SF (based on SNR) improves reliability vs. fixed-SF flooding. Core metric: routing prefers 2-hop SF7+SF7 (82 ms) over 1-hop SF12 (1154 ms) via airtime-based Bellman-Ford.

**Key lesson learned:** Per-link adaptive SF is physically impossible with one SX1262 per node — radio decodes only one SF at a time. Solution: network-wide SF adaptation (all nodes converge independently to same SF by reacting to local SNR).

**Current implementation (Apr 28 2026):**
- `mesh_common.py` — shared protocol: dedup caches, neighbor/route tables, Bellman-Ford, SF adaptation
- `code_esp32.py` — relay node: H/R/D protocol, serial input (TO:<dst>:<msg> or broadcast)
- `code_nrf.py` — BLE gateway: same protocol + BLE notifications + BLE command handler

**Protocol (3 packet types):**
- `H:<src>:<sf>` — HELLO, not relayed, 10s, builds neighbor table + triggers SF adapt
- `R:<orig>:<fwd>:<mid>:<hops>:<cost>` — ROUTE_AD, flooded TTL=5, 30s, Bellman-Ford
- `D:<src>:<dst>:<next_hop>:<mid>:<ttl>:<payload>` — DATA, only next_hop relays unicast

**Routing metric:** SF_AIRTIME = {7:41, 8:72, 9:144, 10:289, 11:577, 12:1154} ms cumulative.

**SF thresholds (5 dB margin):** SF_HOLD escalate-up if SNR < {7:-2.5, 8:-5.0, 9:-7.5...}. Step down after 60s all-good with SF_DOWN thresholds.

**All 8 unit tests pass** (encode/decode round-trips, cross-type rejection, Bellman-Ford logic, adapt_sf logic).

**Next steps:** Flash to hardware, Phase 0 (log SNR baselines), Phase 1 (verify neighbor table builds), dashboard update for H/R/D parsing.

**Why:** Routing tables + next-hop forwarding replaces flooding for unicast. Broadcast (next_hop=0) still floods.
