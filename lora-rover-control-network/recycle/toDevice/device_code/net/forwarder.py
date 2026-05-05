# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Erikas Kadiša

"""Forwarding engine with TTL, duplicate suppression, and ACK retries."""

from config import ACK_TIMEOUT_MS, FORWARD_MAX_RETRIES, MAX_RECENT_SEQS, MAX_TX_QUEUE
from net.scheduler import Scheduler
from protocol.ack import AckManager
from protocol.packets import (
    PACKET_TYPE_TO_ID,
    PacketHeader,
    decode_typed_payload,
    encode_typed_packet,
    packet_type_name,
)
from support.timebase import ticks_ms


_TYPE_ACK = PACKET_TYPE_TO_ID["ACK"]


class Forwarder:
    def __init__(
        self,
        node_id,
        max_tx_queue=MAX_TX_QUEUE,
        max_recent_seqs=MAX_RECENT_SEQS,
        ack_timeout_ms=ACK_TIMEOUT_MS,
        max_retries=FORWARD_MAX_RETRIES,
        scheduler=None,
    ):
        self.node_id = int(node_id)
        self.max_tx_queue = int(max_tx_queue)
        self.max_recent_seqs = int(max_recent_seqs)
        self.ack_timeout_ms = int(ack_timeout_ms)
        self.max_retries = int(max_retries)

        self.scheduler = scheduler or Scheduler()
        self.ack = AckManager()

        self._queue = []
        self._recent = []
        self.logs = []

    def _log(self, event, **fields):
        row = {"event": event}
        row.update(fields)
        self.logs.append(row)

    def _cache_key(self, header):
        ptype = header.type
        if isinstance(ptype, str):
            ptype = PACKET_TYPE_TO_ID.get(ptype.upper(), -1)
        return (int(header.src), int(header.seq), int(ptype))

    def _is_duplicate(self, header):
        key = self._cache_key(header)
        return key in self._recent

    def _remember_packet(self, header):
        key = self._cache_key(header)
        self._recent.append(key)
        if len(self._recent) > self.max_recent_seqs:
            self._recent = self._recent[-self.max_recent_seqs :]

    def _enqueue(self, when_ms, packet_bytes, requires_ack=False, ack_seq=None, ack_dst=None, attempt=0):
        if len(self._queue) >= self.max_tx_queue:
            self._log("queue_drop", reason="queue_full")
            return False
        self._queue.append(
            {
                "when_ms": int(when_ms),
                "packet": packet_bytes,
                "requires_ack": bool(requires_ack),
                "ack_seq": ack_seq,
                "ack_dst": ack_dst,
                "attempt": int(attempt),
            }
        )
        return True

    def queue_outbound(self, header, payload_fields=None, requires_ack=False, now_ms=None):
        """Queue a packet for transmission."""
        now_ms = int(ticks_ms() if now_ms is None else now_ms)
        when_ms = self.scheduler.next_tx_slot(attempt=0, now_ms=now_ms)
        packet = encode_typed_packet(header, payload_fields if payload_fields is not None else b"")
        return self._enqueue(
            when_ms,
            packet,
            requires_ack=requires_ack,
            ack_seq=header.seq if requires_ack else None,
            ack_dst=header.dst if requires_ack else None,
            attempt=0,
        )

    def _build_ack(self, incoming_header):
        header = PacketHeader(
            src=self.node_id,
            dst=incoming_header.src,
            prev_hop=self.node_id,
            next_hop=incoming_header.src,
            seq=incoming_header.seq,
            packet_type="ACK",
            ttl=1,
            flags=0,
            sf=incoming_header.sf,
        )
        payload = {"ack_seq": incoming_header.seq}
        return encode_typed_packet(header, payload)

    def process_incoming(self, header, payload, now_ms=None):
        """Process incoming packet and return action summary.

        Returns dict with keys:
        - duplicate
        - consumed
        - should_forward
        - forward_header
        - ack_scheduled
        """
        now_ms = int(ticks_ms() if now_ms is None else now_ms)
        result = {
            "duplicate": False,
            "consumed": False,
            "should_forward": False,
            "forward_header": None,
            "ack_scheduled": False,
        }

        if header.type == _TYPE_ACK:
            result["consumed"] = True
            try:
                typed = decode_typed_payload("ACK", payload)
                ack_seq = int(typed["ack_seq"])
            except Exception:
                ack_seq = int(header.seq)
            completed = self.ack.complete(ack_seq, header.src)
            self._log("ack_rx", seq=ack_seq, src=header.src, completed=completed)
            return result

        if self._is_duplicate(header):
            result["duplicate"] = True
            result["consumed"] = True
            self._log("drop_duplicate", src=header.src, seq=header.seq, ptype=packet_type_name(header.type))
            return result
        self._remember_packet(header)

        if header.dst == self.node_id:
            result["consumed"] = True
            # Schedule ACK in reserved ACK gap.
            ack_packet = self._build_ack(header)
            ack_when = self.scheduler.ack_slot(now_ms=now_ms)
            scheduled = self._enqueue(ack_when, ack_packet, requires_ack=False)
            result["ack_scheduled"] = scheduled
            self._log("ack_tx_scheduled", dst=header.src, seq=header.seq, scheduled=scheduled)
            return result

        if header.ttl <= 1:
            result["consumed"] = True
            self._log("drop_ttl", src=header.src, seq=header.seq)
            return result

        forward_header = PacketHeader(
            src=header.src,
            dst=header.dst,
            prev_hop=self.node_id,
            next_hop=header.next_hop,
            seq=header.seq,
            packet_type=header.type,
            ttl=header.ttl - 1,
            flags=header.flags,
            sf=header.sf,
        )

        when_ms = self.scheduler.next_tx_slot(attempt=0, now_ms=now_ms)
        packet = encode_typed_packet(forward_header, payload)
        self._enqueue(when_ms, packet, requires_ack=False)

        result["should_forward"] = True
        result["forward_header"] = forward_header
        self._log("forward_queued", src=header.src, dst=header.dst, seq=header.seq, ttl=forward_header.ttl)
        return result

    def _reschedule_retry(self, now_ms, seq, dst, packet, attempt):
        # Retries should happen quickly after timeout; keep timing deterministic.
        when_ms = int(now_ms)
        self._enqueue(
            when_ms,
            packet,
            requires_ack=True,
            ack_seq=seq,
            ack_dst=dst,
            attempt=attempt,
        )

    def process_tick(self, radio, now_ms=None):
        """Run one scheduler tick: send due packets and handle ACK timeouts."""
        now_ms = int(ticks_ms() if now_ms is None else now_ms)

        for key, value in self.ack.expired(now_ms):
            seq, dst = key
            pending = self.ack.pop(seq, dst)
            if pending is None:
                continue
            attempt = int(pending["attempt"]) + 1
            if attempt > self.max_retries:
                self._log("ack_give_up", seq=seq, dst=dst, attempts=attempt)
                continue
            self._reschedule_retry(now_ms, seq, dst, pending["packet"], attempt)
            self._log("ack_retry", seq=seq, dst=dst, attempt=attempt)

        due = []
        future = []
        for item in self._queue:
            if now_ms >= item["when_ms"]:
                due.append(item)
            else:
                future.append(item)
        self._queue = future

        sent_count = 0
        for item in due:
            if radio.send_packet(item["packet"]):
                sent_count += 1
                if item["requires_ack"]:
                    deadline = now_ms + self.ack_timeout_ms
                    self.ack.track(item["ack_seq"], item["ack_dst"], deadline, item["packet"], attempt=item["attempt"])
                    self._log("ack_wait", seq=item["ack_seq"], dst=item["ack_dst"], attempt=item["attempt"])
            else:
                self._log("tx_fail", attempt=item["attempt"])

        return sent_count
