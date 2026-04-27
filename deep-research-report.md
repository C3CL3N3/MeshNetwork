# Design and Analysis of an Adaptive LoRa Mesh Network for IoT

## Executive Summary

This report presents a comprehensive design for a gateway-free **LoRa mesh** network that supports small (5–20), medium (20–200), and large (200+) node deployments. Key features include an adaptive Spreading Factor (SF) selection scheme to maximise throughput while ensuring reliability. We survey LoRa hardware (transceiver chips and modules), radio parameters (SF, bandwidth, coding rate, TX power), and link-quality metrics (RSSI, SNR, packet error rate, ETX). Routing strategies (flooding, tree, AODV-like, RPL-like, opportunistic) and MAC approaches (duty-cycle limits, collision avoidance, scheduling) are compared. Energy management (sleep cycles, duty-cycling, adaptive TX power) and trade-offs in scalability vs latency, reliability and redundancy, and security are discussed. An adaptive-SF algorithm is specified (with thresholds, state-machine flowchart, and pseudo-code). Finally, a test plan is outlined with suggested simulation tools (e.g. NS-3, OMNeT++/FLoRa, LoRaSim【69†L223-L230】) and evaluation metrics (throughput, latency, packet delivery ratio, energy per bit, etc). 

Key recommendations include using low-power LoRa transceivers (e.g. Semtech SX126x), directional antennas where appropriate, SF and TX-power control based on SNR margins, and a hybrid routing/MAC scheme (e.g. clustered flooding or scheduled forwarding) depending on scale. Comparative tables summarize hardware choices and routing/MAC strategies.

## 1. Background and Network Scale

LoRa (Long Range) is a sub-GHz LPWAN physical layer that uses chirp spread spectrum modulation. In **LoRaWAN** networks, end devices communicate in a star topology with high-performance gateways that forward data to a central server. However, this star-of-stars architecture forces **single-hop** links (end-device → gateway) and creates a central-point of failure【70†L304-L313】【70†L362-L370】. For applications in remote or indoor areas, or for peer-to-peer IoT coordination, a **mesh network** of LoRa devices can extend coverage without gateways【70†L304-L313】【70†L362-L370】. In such a mesh, nodes act as both end devices and relays, forming multi-hop paths. 

- **Small networks (5–20 nodes)** might be a local sensor network (e.g. a building, farm); a single mesh cluster often suffices with simple routing (e.g. flooding or a small tree).  
- **Medium networks (20–200 nodes)** could cover a campus or small city area. Here we may segment into clusters or designate relay nodes. Network control (e.g. SF assignment) becomes more important to avoid congestion.  
- **Large networks (200+ nodes)** (e.g. city-wide IoT) face heavy contention and require careful planning. Multiple channels (bands) or hierarchical clustering may be needed. Duty-cycle limits (e.g. <1% in EU868【59†L1040-L1048】) and collisions become critical issues at scale. 

In all cases, devices typically operate in Class A mode (sleeps most of the time, wakes to transmit, then briefly listens). We assume no fixed infrastructure (no Internet-connected gateway), so all communication and coordination happen peer-to-peer.

## 2. Hardware Options

### 2.1 LoRa Transceiver Modules

Key hardware choices center on the LoRa radio chip/module. Table 1 compares popular LoRa radios and modules. All operate at 433/868/915 MHz (region-specific) with TX power up to +20dBm or higher, and very low sleep currents. 

| **Module/Chip**          | **Frequency**    | **Max TX**         | **RX current (typ.)** | **Features**             | **Pros**                        | **Cons**                         |
|--------------------------|------------------|--------------------|-----------------------|--------------------------|----------------------------------|----------------------------------|
| **SX1276/78 (RFM95)**    | 137–1020 MHz     | +20 dBm            | ~10.8 mA【58†L143-L148】    | LoRa (6 SF), FSK, OOK     | Widely used, high link budget (–148dBm)【58†L140-L148】, many modules (e.g. RFM95) | Higher RX current, older design  |
| **SX1261/62 (e.g. LoRa E5)** | 150–960 MHz   | +22 dBm            | ~4.2 mA【56†L13-L18】     | LoRa, highly configurable | Low-power (4.2 mA RX)【56†L13-L18】, +22dBm output, long battery life | Newer; less mature support than SX127x |
| **STM32WL / Murata CMWX1ZZ** | 150–960 MHz | +22 dBm (SX1262 inside) | ~4 mA        | MCU + LoRa transceiver   | Integrated MCU (Cortex-M), very low power, supports LoRa/FLRC | More complex to program, cost  |
| **Microchip RN2483/RN2903** | 433/868 (RN2483), 915 MHz (RN2903) | +14 dBm【25†L31-L39】 | (not stated)         | LoRaWAN-certified module, MCU, UART | Easy to use (built-in stack), FCC/CE certified | Max +14dBm TX, proprietary firmware, less SF control |
| **HopeRF RFM95/RFM96**   | 433/868/915 MHz  | +20 dBm            | ~10 mA               | SX1276/78 on board       | Cheap breakout modules, DIY-friendly | As SX127x (higher power use)    |
| **Pycom LoRa modules (FiPy, GPy)** | 868/915 MHz | +14 dBm           | ESP32+SX1276 (varies) | MCU (WiFi/BLE+LoRa)     | Multi-radio (WiFi, BLE), easy scripting | Higher idle current (ESP32), limited TX power |
| **Antennas**             | –                | –                  | –                     | e.g. 1/4-wave dipole    | 2–3 dBi omni antennas (small)     | Directional (patch) up to 6–9 dBi; requires alignment |
| **Power**                | –                | –                  | –                     | e.g. 3.7V Li-ion, AA    | Easily available; suitable for <100mA peaks | TX (~100mA) requires decent source; consider batteries or solar panels |

- *Notes:* SX1276/78 modules (e.g. RFM95, Ai-Thinker Ra-02) achieve receiver sensitivity up to –148dBm and can output +20dBm【58†L140-L148】. The newer SX1262 (as on LoRa E5 or RAK831) pushes +22dBm and uses only ~4.2mA in RX【56†L13-L18】, extending battery life. Integrated MCU+LoRa chips like STM32WL reduce BOM count but require more complex firmware. Antennas should be tuned for the band (e.g. quarter-wave ~16.4 cm at 433 MHz, 8.2 cm at 868 MHz) and have a ground plane for good radiation. Gain (2–9 dBi) trades off range vs coverage area. High-gain or directional antennas increase range but limit coverage footprint.

Table 1 compares **TX power** and **RX current** (key for energy) from datasheets【56†L13-L18】【58†L143-L148】. For example, SX1276 draws ≈10.8 mA RX【58†L143-L148】, whereas SX1262 draws only ~4.2 mA【56†L13-L18】. All chips can sleep deep (sub-µA). Power should be a regulated ~3.3 V supply (batteries or supercaps). Duty cycles (regulatory) also affect battery lifetime.

## 3. Radio Parameters

Each LoRa link is configured by **Spreading Factor (SF)**, **Bandwidth (BW)**, **Coding Rate (CR)**, and **TX Power**. 

- **Spreading Factor (SF 7–12):** Higher SF increases symbol length (time-on-air) and sensitivity, but lowers data rate. For 125 kHz bandwidth, SF7 gives ~5.5 kbps and –123 dBm sensitivity; SF12 gives ~0.3 kbps and –137 dBm sensitivity【58†L174-L181】. Each +1 SF adds ~3 dB link budget. In practice, start with SF9 or 10 for moderate links, and raise SF for weak links【58†L174-L181】. SF12 (max range) has ~5× time-on-air vs SF7.  
- **Bandwidth (7.8–500 kHz):** Common settings are 125, 250, 500 kHz. 125 kHz is standard (best sensitivity)【58†L199-L207】. Doubling BW (to 250 kHz) doubles data rate and reduces sensitivity by ~3 dB; 500 kHz doubles again. Wider BW supports higher throughput but shortens range. A mixed-BW scheme can be used (narrow BW on long hops, wide BW on short hops).  
- **Coding Rate (CR):** Forward error correction. LoRa supports 4/5 to 4/8. 4/5 (20% overhead) is default【58†L203-L207】. Higher CR (e.g. 4/8) adds redundancy, improving reliability in noisy conditions at the cost of doubling time-on-air. We recommend 4/5 for normal operation, and increase CR only if repeated losses occur on a critical link.  
- **TX Power:** Typically up to +20–22 dBm (100–160 mW) on most modules【58†L143-L148】【56†L13-L18】. Use the minimum power needed to meet the SNR margin to save energy and reduce interference. Regional limits apply (e.g. EU868 channels are often limited to +14 dBm if duty-cycled, or require LBT for higher power). High TX improves range (each +3 dB doubles range) but costs battery. Adaptive TX control can complement SF selection.

LoRa parameters are tuned link-by-link. Table 2 (below) summarises SF vs data rate/sensitivity for 125 kHz BW【58†L174-L181】:

| **SF** | **Data Rate (kbps)** | **Sensitivity (dBm, 125kHz BW)** | **Typical Use** |
|:------:|:-------------------:|:--------------------------------:|:---------------:|
| SF7    | 5.47                | –123      | Short-range, high update rate【58†L174-L181】 |
| SF8    | 3.13                | –126      | Urban/suburban moderate range  |
| SF9    | 1.76                | –129      | Mixed indoor/outdoor |
| SF10   | 0.98                | –132      | Outdoor/suburban long range |
| SF11   | 0.54                | –134.5    | Rural/outdoor far range |
| SF12   | 0.29                | –137      | Maximum range/deep indoor【58†L174-L181】 |

*Table 2: LoRa data rates and receiver sensitivity vs SF (125 kHz BW)【58†L174-L181】.*

## 4. Link-Quality Metrics

Routing and adaptation decisions use link-quality metrics. Common metrics in LoRa mesh include:

- **RSSI (Received Signal Strength):** Absolute signal power at receiver (dBm). Useful for antenna pointing but includes noise. High RSSI alone is insufficient if noise is also high.  
- **SNR (Signal-to-Noise Ratio):** Measured by the LoRa demodulator for each packet. LoRa can decode negative SNR signals. For example, SF7 requires only about –7.5 dB SNR to decode, whereas SF12 can decode down to about –20 dB【41†L234-L240】. Thus a packet with SNR above these thresholds is likely reliable. In general, maintain a margin (e.g. ≥5 dB above the SF threshold) for robustness.  
- **PER (Packet Error Rate):** The fraction of lost or corrupted packets on a link. High PER indicates poor link. PER can be estimated by counting ACKs or CRC fails.  
- **ETX (Expected Transmission Count):** An integrated metric: ETX = 1/(packet delivery ratio). It estimates the expected number of transmissions (including retransmits) to deliver a packet. Paths with low ETX are preferred. ETX requires measuring PER or using ACK statistics.  
- **Other:** Some routing use **LQI** (Link Quality Indicator) or **RSSIavg**. In practice, SNR and PER are most directly linked to LoRa performance.

For example, if a receiver reports RSSI = –100 dBm with SNR = –5 dB (on SF7), the link is borderline and may be improved by raising SF. If SNR is well above the threshold, SF can be lowered to boost rate. A rule-of-thumb (from LoRaWAN field guides) is: “if RSSI > –115 dBm and SNR > –10 dB, link is healthy; below that expect losses”【41†L234-L240】. These metrics are used by adaptive algorithms (see below) and by routing metrics (e.g. choosing routes with higher SNR or lower PER).

## 5. Adaptive Spreading Factor (SF) Algorithms

To maximise throughput while preserving reliability, each link’s SF should adapt to channel conditions. LoRaWAN’s **Adaptive Data Rate (ADR)** is a centralized server-driven scheme, but in a peer-to-peer mesh we need distributed SF control. Adaptive SF algorithms adjust SF (and possibly TX power) based on link metrics (SNR, PER, ETX). Key approaches:

- **Centralised (gateway-driven):** In LoRaWAN, the network server collects SNR from multiple gateways and decides SF/TX for each node via ADR commands【29†L63-L72】. In a mesh without a server, a similar concept could be a designated coordinator node, but this introduces single-point dependency.  
- **Distributed (device-driven):** Each node dynamically tunes SF. For example, an **iterative SF inspection** scheme (ASFS) lets a transmitter/receiver pair “test” different SFs to find the fastest reliable rate【46†L500-L509】. One implementation (Kim et al.) synchronised SFs without extra packets by sweeping through SF values and checking if the peer locks on【46†L500-L509】.  
- **Metrics and rules:** A simple rule is: measure link SNR or PER at the current SF. If SNR >> SF-threshold (e.g. margin >5–10 dB), *lower* SF by 1 (faster rate). If SNR << threshold or PER is high, *raise* SF by 1. For example, if SNR > –2 dB on SF9 (threshold ~–12.5 dB), try SF8. Conversely, if SNR < –15 dB on SF9, go to SF10. These thresholds stem from datasheet values (SF7: –7.5 dB; SF12: –20 dB【41†L234-L240】). One can also use ACK feedback: if a packet is unacknowledged, assume link too weak and increase SF or TX power. 
- **State machine:** The node may have states like *Probationary* (testing SFs) and *Steady*. Initially start at a safe SF (e.g. 12), then step down until errors rise, then settle. Periodically re-test (e.g. every few minutes) to adapt to environmental changes (wind, obstacles). 

```mermaid
flowchart TD
    A([Start / Initialization]) --> B{Have link metric?}
    B -- Yes --> C{SNR >= high_thresh?}
    B -- No --> D[Send probe / beacon]
    C -- Yes --> E[SF = max(SF-1, SF_min)  // try lower SF (faster)]
    C -- No --> F{SNR <= low_thresh?}
    F -- Yes --> G[SF = min(SF+1, SF_max)  // use higher SF (more robust)]
    F -- No --> H[Keep SF]
    D --> I[Receive metric (SNR/PER)]
    I --> C
    E --> I
    G --> I
    H --> I
```

*Figure 1: Flowchart of a simple distributed SF-adaptation algorithm. Nodes measure link SNR or PER and adjust SF up/down based on thresholds (high_thresh ≈ –5 dB above needed SNR for current SF; low_thresh ≈ current SF’s SNR limit)【41†L234-L240】.*

**Pseudocode example:**  
```
function adapt_SF(link):
    SNR = measure_SNR(link)
    if SNR > (SF_threshold(link.SF) + margin_high):
        link.SF = max(link.SF - 1, SF_min)
    elif SNR < (SF_threshold(link.SF) - margin_low):
        link.SF = min(link.SF + 1, SF_max)
    // else keep current SF
```
Where `SF_threshold(sf)` returns the minimum SNR (in dB) needed for that SF (e.g. –7.5 for SF7, –20 for SF12【41†L234-L240】). Margins (`margin_high`, `margin_low`) can be a few dB to avoid oscillation. Retransmission counts or ETX could also trigger adjustments.

Adaptive SF can be **link-by-link** (each neighbor pair negotiates an SF) or network-wide (all nodes use same SF in synchronous schemes). A hybrid approach may work: e.g. flood broadcasts at SF11 for reach, then set specific unicast links to SF8 where possible.

## 6. Routing Strategies for Mesh

In a mesh of LoRa nodes, data must hop between nodes. We consider several classes of routing/MAC strategies, summarised in Table 3.

| **Strategy**               | **Type**     | **Pros**                                             | **Cons**                                           | **Scale Suitability**     |
|----------------------------|--------------|------------------------------------------------------|----------------------------------------------------|---------------------------|
| **Flooding (Broadcast)**   | No routing table; transmit on all nodes (e.g. LoRaBlink) | Very simple; implicit redundancy; good for discovery/broadcast 【45†L690-L699】 | High airtime usage; collisions in dense networks; not energy-efficient | Small–medium (best for <50 nodes) |
| **Spanning Tree / Parent-Child** | Tree topology (static routes) | Low control overhead; deterministic paths | Single point of failure at root; not robust to node changes | Medium (20–100 nodes) |
| **AODV-like (On-demand)** | Reactive routing | Finds dynamic paths; no overhead if idle | Route discovery latency; extra control packets; memory-limited nodes | Medium, dynamic scenarios |
| **RPL (DODAG)**            | Proactive DAG (IPv6) | Well-suited for many-to-one traffic; supports ETX metric; loop avoidance | Relatively complex; header overhead; may violate LoRa payload size/duty-cycle | Medium–large (if IPv6 needed) |
| **Opportunistic / Gossip** | Hybrid/Flooding | Increased reliability via overhearing; adaptable | Complex logic; potential for duplicates; unpredictable delay | Niche; complex to implement |
| **Relay-Only (No Routing)** | Pure retransmission | Very simple (no addressing); each node just forwards received packets【51†L143-L147】 | Wastes air (all floods); no path optimization【51†L143-L147】 | Very small (tens of nodes); emergency/beacon scenarios |
| **Scheduled TDMA**         | MAC-level timeslotting | Avoids collisions, supports duty-cycle; energy efficient if sync | Requires time synchronization; global schedule management | Medium–large (if infrastructure sync available) |

*Table 3: Comparative routing/MAC strategies for LoRa mesh, with pros/cons and recommended network size【45†L690-L699】【51†L143-L147】.*

- **Flooding:** Every node rebroadcasts each packet (often once). Protocols like LoRaBlink use this for low-cost mesh【45†L690-L699】. Flooding achieves fast dissemination and high reliability (multiple path diversity), but wastes airtime and energy. Collisions become severe as node count grows. It suits small networks or occasional broadcast messages, not high-throughput data.  
- **Tree/Cluster:** Nodes form a tree (perhaps via a root or cluster-head) and route data along parent-child links. This reduces redundant transmissions. It requires a route discovery or manual configuration. A loss of a parent breaks a branch. Good for moderate networks where data converge to a sink (like a designated collector or an external gateway).  
- **AODV-like:** A route discovery is initiated on-demand (flooded request, unicast reply) to establish a path. Routes can adapt to changes. Downside is the route setup delay and storage of route tables in memory-limited nodes. Literature (e.g. Zorbas et al.) has experimented with AODV over LoRa【51†L109-L117】.  
- **RPL (Routing Protocol for LLNs):** A tree-based routing (DODAG) often used in 6LoWPAN. RPL can use link metrics (ETX) to form a DAG toward a root. Some works port RPL to LoRa (nodes running 6LoWPAN/Contiki). RPL supports IPv6, but has overhead (headers, DAO/Dis/DODAG control messages) and may violate LoRa duty constraints if misconfigured.  
- **Opportunistic/Gossip:** Nodes overhear neighbors and decide who should forward based on local info (e.g. geographic forwarding or ETX). This can exploit broadcast nature but is complex. Few practical LoRa implementations exist.  
- **Relay-only (Pure Flooding):** As in some LoRaWAN proposals, certain nodes simply act as “repeaters” and rebroadcast everything they hear【51†L143-L147】. This is the simplest: no addressing, no routing tables. But it fully floods every message and quickly hits the duty-cycle limit. As noted by Cotrim, such relaying is easier to implement, but for large networks routing saves many transmissions【51†L143-L147】.  
- **Scheduled MAC (TDMA):** An overlay scheduling (e.g. every node has a time slot or uses coordinated wake-up) avoids collisions and can respect duty-cycle. LoRa’s long packets make fine-grained TDMA challenging, but coarse schedules (e.g. slotted flooding or wake periods) can help. Time sync (GPS or protocols) is needed. Works well in deterministic industrial IoT if complexity is manageable.

**Recommendation:** For **small meshes**, flooding or simple relaying can work, since overhead is low. For **medium to large meshes**, a structured routing (AODV or RPL) or cluster-tree is better to avoid broadcast storms. Often a hybrid is used: e.g. initial flooding for discovery, then tree for data. Notably, CT-LoRa (a recent research protocol) uses **flooding plus concurrent transmissions** to boost reliability【45†L690-L699】. In general, one should minimize retransmissions due to regulatory limits; carefully chosen routing/MAC can improve scalability.

## 7. MAC and Duty-Cycle Considerations

LoRa operates under regulatory limits (e.g. ETSI EN300.220 in EU), which typically enforce a **duty cycle** (e.g. 1% on each channel【59†L1040-L1048】). Thus, each node can transmit only ~36 s per hour per channel. In a mesh, this is a hard limit: more nodes or retransmits risk saturating allowed airtime. 

- **Duty-cycle:** Design so that no node (or channel) exceeds its duty cycle. Use fewer (longer) packets, or spread traffic across multiple channels (bands). EU nodes often use a combination of default channels (each <1% duty【59†L1040-L1048】). ADR/TX power control helps reduce airtime.  
- **Collision Avoidance:** LoRa itself does not have CSMA/CA (like IEEE 802.15.4). However, the SX126x and SX127x chips offer a *CAD (Channel Activity Detection)* mode to detect LoRa preambles. A node could do a quick CAD before TX to avoid obvious collisions, although CAD only detects LoRa preambles of the same SF/BW, and adds delay. In practice, random back-off and low duty (asynchronous ALOHA) is common in LoRaWAN. For mesh, one can use randomized transmission times to reduce collision probability.  
- **Channel diversity:** Use multiple frequency channels (and orthogonal spreading factors) to reduce collisions. LoRa gateway chips can demodulate different SFs simultaneously, but a single-radio node can typically only receive one SF at a time. Careful channel assignment (e.g. time-slotted hopping) can improve throughput.  
- **Scheduling:** In larger or critical networks, time-slotted schemes help. For instance, some multi-hop LoRa experiments use periodic or event-driven time slots to avoid concurrent transmissions【70†L473-L480】. A TDMA-like schedule (every node or cluster has a reserved slot) virtually eliminates collisions but requires clock sync. For battery-powered nodes, sleep/wake scheduling (Class B/C wake slots) can also be applied at the network layer.

Overall, MAC design in LoRa mesh is about balancing simplicity (random ALOHA-like access) with regulatory compliance and collision avoidance. Medium-density networks benefit from a modest protocol (e.g. random delays + ACKs), while high-density may need more coordination.

## 8. Energy Management

LoRa nodes are battery-powered in most IoT settings. Energy use is dominated by radio, especially transmissions. Key strategies:

- **Sleep cycles:** Nodes should sleep (radio off) as much as possible. Use low-power modes between transmissions. For example, implement Class A behavior: transmit, then open two short RX windows, then sleep until next scheduled TX.  
- **Duty-cycling the radio:** In-between frames, turn off the LoRa radio (which can draw ~10 mA in RX【58†L143-L148】) to near µA levels. Use wake-on-interrupt or low-power timers.  
- **Adaptive TX power:** Transmit at the minimum power that yields reliable reception. If link quality is high, reduce TX power by a few dB to save battery. LoRa hardware supports fine TX-power steps.  
- **Efficient retransmit strategy:** Limit the number of retries/ACKs. Excess ARQ floods drain energy. Possibly use fountain codes or forward error correction for critical data instead of retransmit.  
- **Duty cycle compliance:** Overusing duty cycle not only violates regs but implies wasted (or even illegal) energy use. Keep transmissions short and infrequent if battery-limited.  

For example, using SF7 instead of SF12 for a close neighbor reduces time-on-air ~16×【58†L174-L181】, saving proportional energy at the radio. Asynchronous duty-cycling also reduces collisions and idle listening. Some works allow nodes to harvest energy (solar) in rural setups, but this adds hardware complexity.

## 9. Scalability and Latency Trade-offs

A larger network increases overall capacity but also contention and delays:

- **Scalability:** Adding nodes increases aggregate traffic. LoRa’s limited bandwidth means that throughput per node drops as node count rises, especially if many are within mutual range. Flooding protocols do not scale well (each extra node multiplies transmissions). Tree or routing protocols scale better because each packet is forwarded once per hop. Nonetheless, the regulatory duty limits (e.g. 1% per channel) impose a hard cap on network load. Carefully dimension number of channels and transmission frequency. Simulation studies show that spreading factors and channel diversity significantly impact capacity. 
- **Latency:** Multi-hop adds delay: each hop incurs TX time plus possible queuing. Flooding can have low latency (parallel broadcasts), but also more collisions. Route setup (AODV) adds initial delay. SF selection also affects latency: higher SF (slower data rate) means longer packets. In a mesh, choose SF minimal for link reliability to reduce airtime.  
- **Reliability vs Throughput:** A network aiming for reliability may send redundant packets (flood, high SF), but at cost of throughput and latency. Conversely, pushing maximum data rate (low SF, no retries) risks loss. Adaptive SF (Sec. 5) helps balance this trade-off. For example, the ASFS scheme improved mesh throughput by ~3× over static SF usage【46†L500-L509】. 
- **Density effects:** In dense deployments, collision risk soars. Techniques like CAD or LBT (in non-EU regions) become more valuable. In contrast, sparse rural networks can use high SF for long links, at expense of per-hop delay (hours between packets might be acceptable if traffic is low).

In summary, design must tune mesh size and traffic for the use-case. E.g., a large network might shard into multiple channels or subnets, while a small one can use simpler broadcast schemes.

## 10. Reliability and Redundancy

Ensuring that messages reach their destination is critical:

- **Acknowledgements and Retransmissions:** For unicast, use ACK packets to confirm delivery. Retransmit up to a limit. LoRa’s long airtime makes many retries expensive, so limit to a few attempts.  
- **Multi-path/Flooding:** Redundant paths (e.g. multiple parents or cluster heads) improve PDR. Flooding inherently provides duplication; in routing schemes, consider sending critical data via two disjoint routes (if energy allows).  
- **Forward Error Correction:** The built-in LoRa FEC (coding rate) already adds redundancy at PHY. Application-layer FEC (e.g. systematic erasure codes) can guard against packet loss without full retransmit.  
- **Beacons/Topology Refresh:** Periodic low-rate beacons or “hello” messages can update link statuses, so that nodes detect and avoid failed neighbors.  
- **Adaptive SF:** By raising SF on a weak link, we trade airtime for fewer bit-errors. Coupling SF control with reattempts boosts link reliability without manual tuning. 

Redundancy must be weighed against duty limits. Often one chooses a reliability target (e.g. PDR ≥90%) and then adapts SF and routing to meet it, rather than flooding blindly.

## 11. Security Considerations

Even in a mesh, we must secure communications:

- **Encryption:** Use AES-128 encryption (as in LoRaWAN) to encrypt payloads, preventing eavesdropping. LoRa chips often support hardware AES. Each link could use shared keys or unique link keys.  
- **Authentication:** Ensure nodes authenticate each other (e.g. message MIC or HMAC) to prevent spoofing. LoRaWAN uses network/app keys; a mesh could use a pre-shared network key or device IDs.  
- **Replay Protection:** Nonces or frame counters should be used to prevent replay attacks. LoRaWAN frames include a frame counter; a mesh protocol should similarly track nonces per neighbor.  
- **Key Management:** For large deployments, manual key distribution is impractical. Over-the-air activation (OTAA) akin to LoRaWAN, or dynamic key exchange (e.g. Diffie-Hellman) could be used. This adds complexity.  
- **Physical Security:** LoRa’s modulation resists some jamming (it can decode below noise). However, intentional interference (barrage jamming) can block entire channels. Frequency hopping or channel diversity can mitigate. Also, ensure antenna connectors and cable are well shielded (water ingress or corrosion can kill nodes【41†L229-L237】).
- **Network Integrity:** A mesh lacks a central monitor, so a compromised node could misroute traffic. Watchdogs or periodic integrity checks (e.g. round-trip consistency) help detect anomalies.

In summary, use standard lightweight security (AES, MICs) per link. If implementing fully ad-hoc, a lightweight “mesh security” layer (as in Zigbee or Thread) would be ideal, but even LoRaWAN’s own MAC security features can be adapted to a mesh context.

## 12. Proposed Architecture

Based on the above, a recommended architecture is:

- **Flat, Peer-to-Peer Mesh:** All nodes run the same code and can forward packets. No dedicated gateway. One or a few nodes may connect to the Internet (if needed) as border routers, but are not required for mesh functioning.  
- **Multi-Hop Routing with Local SF Control:** Each node maintains a neighbor table (RSSI/SNR stats). Data is routed via AODV-like or RPL/DODAG to a sink or gateway node if external access is required. Nodes adjust SF per-link as described.  
- **Channel Plan:** Use multiple 125kHz channels (per regional plans) to spread load. For example, EU nodes could use the default three 125kHz channels plus additional channels if available.  
- **MAC:** Use asynchronous access with low-duty random backoff, plus acknowledgements. Optionally, reserve time-slots for control beacons or synchronized flooding periods.  
- **Power:** Nodes run on batteries with daily wake-ups. Critical routers can be mains-powered or have larger batteries.

A sample mesh topology (with SF labels) is shown below. Nodes dynamically form links (shown) based on range and SF:

```mermaid
graph LR
  subgraph "Cluster 1 (close range)"
    A[Node A] -- SF7 --> B[Node B]
    A -- SF8 --> C[Node C]
    B -- SF9 --> D[Node D]
    C -- SF9 --> D
  end
  subgraph "Cluster 2 (farther out)"
    E[Node E] -- SF10 --> F[Node F]
    D -- SF11 --> E
    C -- SF12 --> G[Node G (edge)]
  end
  style A fill:#ccf,stroke:#333,stroke-width:1px
  style D fill:#cfc,stroke:#333,stroke-width:1px
  style G fill:#fcc,stroke:#333,stroke-width:1px
```

**Figure 2:** Example LoRa mesh topology. Edges show active links and their SF. Nodes adapt SF per link (e.g. A–B uses SF7 for high rate, while D–E at long range uses SF11). Critical routers (green) handle inter-cluster traffic; edge node (red) is on the fringe. 

In this design, each node periodically exchanges small "hello" messages with neighbors (using CAD or short preambles) to measure SNR/RSSI. Routing tables or DODAG parents are built from these metrics. The network is self-healing: if a link fails, alternative routes (via different neighbors or SF changes) are used. Table 4 (above) guides the choice of routing/MAC by network size. 

**Parameter settings (typical):** SF=7–12, BW=125 kHz, CR=4/5 by default【58†L203-L207】. TX power should be set per region (e.g. +14 dBm EU), but adapt downward when SNR margins are high. Duty-cycle 1% must not be exceeded on any channel【59†L1040-L1048】. 

## 13. Adaptive SF Algorithm (Detailed)

Building on the flowchart above (Figure 1), the SF adaptation logic can be summarised:

1. **Initialization:** Start transmissions at a high (safe) SF (e.g. 11 or 12) to ensure connectivity.  
2. **Probing:** Periodically send a test packet or include a probe bit in normal traffic. Neighbors measure SNR and return an ACK with the measurement.  
3. **Decision:** For each neighbor link, compare the measured SNR (or recent PER) against thresholds. If SNR is significantly above (e.g. +5 dB) the required threshold for the current SF, the node decrements SF (faster mode). If SNR falls below (e.g. –5 dB) the threshold, increment SF. Update the link configuration accordingly.  
4. **Update:** The node must then use the new SF for subsequent packets on that link. If ACKs fail consistently at new SF, revert back.  
5. **Repeat:** Continually monitor and adjust. One can also adapt transmission power similarly: if link is very good, try reducing TX by 3 dB, etc. 

**Example thresholds:** Using [41], SF7 needs ~–7.5 dB SNR; SF12 needs ~–20 dB. So a node with SF9 (threshold ~–12.5 dB) might use margin_high=5 dB, margin_low=5 dB. If SNR ≥ –7.5 dB, drop to SF8; if SNR ≤ –17.5 dB, raise to SF10.

Pseudocode for one link could be:

```pseudocode
function adapt_SF(link):
    measured_SNR = link.getLastSNR()
    threshold = SNR_threshold_for_SF(link.SF)
    if measured_SNR >= threshold + 5:
        link.SF = max(link.SF - 1, 7)
    else if measured_SNR <= threshold - 5:
        link.SF = min(link.SF + 1, 12)
    // else keep link.SF
    link.applySF()  // configure radio
```

In practice, the algorithm may include hysteresis (wait some packets between changes) to avoid oscillation. It may also use **ETX**: if more than N consecutive packets fail (implying PER is high), assume link too weak and raise SF.

## 14. Test Plan and Evaluation

To validate the design, both **simulation** and **field experiments** are recommended:

- **Simulation Tools:** Use network simulators that support LoRa/LoRaWAN. Examples include **NS-3** with a LoRaWAN module, **OMNeT++ with FLoRa**, and **LoRaSim**. These have been widely used to assess LoRa networks【69†L223-L230】. They allow modeling of large node counts, propagation effects, and protocol behavior. We suggest starting with FLoRa (open-source OMNeT++ framework) or NS-3 (with available LoRa modules) for packet-level simulation.  
- **Key Metrics:** Evaluate *Packet Delivery Ratio (PDR)*, *end-to-end latency*, *throughput*, and *energy consumption* (per packet or per time). Also measure *collision rate* (percentage of packets lost due to overlap), *network lifetime* (time until first battery dies), and *routing overhead* (percentage of control traffic).  
- **Scenarios:** Simulate at least three scenarios:  
  1. **Small network (10–20 nodes)**: Random placement within ~1 km², low traffic (1 packet/min). Test flooding vs AODV routing. Evaluate link adaptation.  
  2. **Medium network (50–100 nodes)**: Larger area (multi-km²), multiple hops needed. Include obstacles or varied SNR. Measure scalability of routing and duty-cycle usage.  
  3. **Large network (200+ nodes)**: Possibly grid or clustered distribution, heavier traffic (e.g. 1 pkt/10s). Test scheduling (if used) vs pure ALOHA.  
- **Parameter Sweeps:** Vary spreading factor adaptation (on/off), TX power control, and node density. Analyze trade-offs.  
- **Testbed:** For real tests, use evaluation boards (e.g. Arduino + SX1262 modules or development kits) in a controlled area. Deploy a mini-mesh (5–10 nodes) in a building or field. Measure actual RSSI/PER vs distance, test SF adaptation. Tools: use serial logs or The Things Network console to inspect metadata.  

**Validation:** Compare simulation vs theory. For instance, check that adaptive SF indeed doubles throughput under good links (as suggested by ASFS results【46†L500-L509】). Ensure duty-cycle compliance (e.g. no channel’s airtime > 1%). Use power meters or radio chip current readings to confirm sleep vs active currents match spec.

By combining official LoRa Alliance/ Semtech parameter studies and recent academic protocols【46†L500-L509】【70†L304-L313】, this design balances throughput, reliability, and energy in various IoT deployment scenarios.

