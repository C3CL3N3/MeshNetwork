# SPDX-FileCopyrightText: 2026 Student Lab - COMP 4531 - HKUST
# SPDX-License-Identifier: MIT
#
# CircuitPython SX1262 driver — written from scratch against the SX1262 datasheet.
#
# Improvements over the stock library:
#   * Hardware CAD (Channel Activity Detection) — real channel sensing via SetCad()
#   * TX-done detection via IRQ register polling — no blind sleep
#   * Non-blocking async RX — recv_start() / recv_poll()
#   * CRC / header error detection and reporting
#   * Instantaneous RSSI — getRSSIInst()
#   * LBT (Listen-Before-Talk) using hardware CAD — send_lbt()
#   * RF switch managed internally — no manual toggling in firmware
#   * LDRO auto-configured from SF/BW

import time
import random

# ── SX1262 op-codes ───────────────────────────────────────────────────────────
_SET_STANDBY          = 0x80
_SET_TX               = 0x83
_SET_RX               = 0x82
_SET_CAD              = 0xC5
_SET_REGULATOR_MODE   = 0x96
_CALIBRATE            = 0x89
_CALIBRATE_IMAGE      = 0x98
_SET_PA_CONFIG        = 0x95
_SET_DIO_IRQ_PARAMS   = 0x08
_GET_IRQ_STATUS       = 0x12
_CLR_IRQ_STATUS       = 0x02
_SET_DIO3_TCXO        = 0x97
_SET_RF_FREQUENCY     = 0x86
_SET_PKT_TYPE         = 0x8A
_SET_TX_PARAMS        = 0x8E
_SET_MOD_PARAMS       = 0x8B
_SET_PKT_PARAMS       = 0x8C
_SET_CAD_PARAMS       = 0x88
_SET_BUF_BASE_ADDR    = 0x8F
_WRITE_BUF            = 0x0E
_READ_BUF             = 0x1E
_GET_RX_BUF_STATUS    = 0x13
_GET_PKT_STATUS       = 0x14
_GET_RSSI_INST        = 0x15

# ── IRQ bit masks ─────────────────────────────────────────────────────────────
_IRQ_TX_DONE      = 0x0001
_IRQ_RX_DONE      = 0x0002
_IRQ_HEADER_ERR   = 0x0020
_IRQ_CRC_ERR      = 0x0040
_IRQ_CAD_DONE     = 0x0080
_IRQ_CAD_DETECTED = 0x0100
_IRQ_TIMEOUT      = 0x0200

# ── Bandwidth kHz -> register value ──────────────────────────────────────────
_BW_REG = {
    7.81: 0x00, 10.42: 0x08, 15.63: 0x01, 20.83: 0x09,
    31.25: 0x02, 41.67: 0x0A, 62.5: 0x03,
    125.0: 0x04, 250.0: 0x05, 500.0: 0x06,
}

# ── CAD peak detection threshold per SF (from Semtech AN) ────────────────────
_CAD_PEAK = {7: 22, 8: 22, 9: 22, 10: 23, 11: 24, 12: 24}

# ── Image calibration bands (freq1, freq2) ────────────────────────────────────
def _image_cal_bytes(freq_mhz):
    if   freq_mhz < 446:  return 0x6B, 0x6F
    elif freq_mhz < 512:  return 0x75, 0x81
    elif freq_mhz < 783:  return 0xC1, 0xC5
    elif freq_mhz < 866:  return 0xD7, 0xDB
    else:                 return 0xE1, 0xE9


class SX1262:
    """
    SX1262 LoRa driver for CircuitPython.

    Constructor args (same positional order as the stock library for drop-in
    replacement):
        spi      -- busio.SPI instance
        sck/mosi/miso -- ignored (already encoded in spi), kept for compat
        nss      -- chip-select DigitalInOut
        dio1     -- IRQ line DigitalInOut (input)
        rst      -- reset DigitalInOut
        busy     -- busy pin DigitalInOut (input)
        rf_sw    -- (keyword, optional) RF-switch DigitalInOut; if provided
                   the driver toggles it True=TX / False=RX automatically.
    """

    def __init__(self, spi, sck, mosi, miso, nss, dio1, rst, busy, rf_sw=None):
        import digitalio

        # Accept raw microcontroller pins OR already-wrapped DigitalInOut objects.
        def _out(pin):
            if isinstance(pin, digitalio.DigitalInOut):
                pin.direction = digitalio.Direction.OUTPUT
                return pin
            p = digitalio.DigitalInOut(pin)
            p.direction = digitalio.Direction.OUTPUT
            return p

        def _in(pin):
            if isinstance(pin, digitalio.DigitalInOut):
                pin.direction = digitalio.Direction.INPUT
                return pin
            p = digitalio.DigitalInOut(pin)
            p.direction = digitalio.Direction.INPUT
            return p

        self._spi  = spi
        self._nss  = _out(nss);  self._nss.value = True
        self._rst  = _out(rst);  self._rst.value = True
        self._dio1 = _in(dio1)
        self._busy = _in(busy)

        if rf_sw is None:
            self._rf_sw = None
        elif isinstance(rf_sw, digitalio.DigitalInOut):
            self._rf_sw = rf_sw
        else:
            self._rf_sw = _out(rf_sw)

        self._sf        = 7
        self._bw        = 125.0
        self._cr        = 5
        self._freq      = 912.0
        self._last_rssi = 0
        self._last_snr  = 0.0
        self._rx_active = False

    # == Low-level SPI =========================================================

    def _wait_busy(self, ms=100):
        end = time.monotonic_ns() + ms * 1_000_000
        while self._busy.value:
            if time.monotonic_ns() > end:
                raise RuntimeError("SX1262 busy timeout")

    def _xfer(self, out_buf):
        """Full-duplex SPI transaction. Returns bytearray of same length."""
        resp = bytearray(len(out_buf))
        self._wait_busy()
        while not self._spi.try_lock():
            pass
        try:
            self._nss.value = False
            self._spi.write_readinto(out_buf, resp)
            self._nss.value = True
        finally:
            self._spi.unlock()
        return resp

    def _write(self, out_buf):
        """Write-only SPI transaction (no result needed)."""
        self._wait_busy()
        while not self._spi.try_lock():
            pass
        try:
            self._nss.value = False
            self._spi.write(bytearray(out_buf))
            self._nss.value = True
        finally:
            self._spi.unlock()

    def _cmd(self, opcode, *args):
        """Send opcode + args; returns full response bytearray."""
        return self._xfer(bytearray([opcode] + list(args)))

    def _cmd_r(self, opcode, n_dummy, n_result):
        """Send opcode + n_dummy NOP bytes, return n_result result bytes."""
        buf = bytearray([opcode] + [0x00] * (n_dummy + n_result))
        r   = self._xfer(buf)
        return r[n_dummy + 1:]

    # == IRQ helpers ===========================================================

    def _get_irq(self):
        r = self._cmd_r(_GET_IRQ_STATUS, 1, 2)
        return (r[0] << 8) | r[1]

    def _clr_irq(self, mask=0xFFFF):
        self._cmd(_CLR_IRQ_STATUS, (mask >> 8) & 0xFF, mask & 0xFF)

    def _set_irq(self, mask):
        """Route mask to global IRQ and DIO1; silence DIO2/DIO3."""
        self._cmd(_SET_DIO_IRQ_PARAMS,
                  (mask >> 8) & 0xFF, mask & 0xFF,
                  (mask >> 8) & 0xFF, mask & 0xFF,
                  0x00, 0x00, 0x00, 0x00)

    def _poll_irq(self, mask, timeout_ms):
        """Spin-wait for any bit in mask. Returns irq word or 0 on timeout."""
        end = time.monotonic_ns() + timeout_ms * 1_000_000
        while True:
            irq = self._get_irq()
            if irq & mask:
                return irq
            if time.monotonic_ns() > end:
                return 0

    # == Packet status =========================================================

    def _fetch_pkt_status(self):
        r = self._cmd_r(_GET_PKT_STATUS, 1, 3)
        self._last_rssi = -(r[0] >> 1)
        snr_raw = r[1] if r[1] < 128 else r[1] - 256
        self._last_snr  = snr_raw / 4.0

    # == RF switch helpers =====================================================

    def _tx_mode(self):
        if self._rf_sw:
            self._rf_sw.value = True

    def _rx_mode(self):
        if self._rf_sw:
            self._rf_sw.value = False

    # == Initialisation ========================================================

    def begin(self, freq=912.0, bw=125.0, sf=7, cr=5, power=22,
              tcxoVoltage=1.8, useRegulatorLDO=False):
        """Configure radio. Call once at startup; call again to change SF/freq."""
        self._sf = sf; self._bw = bw; self._freq = freq; self._cr = cr

        # Hard reset
        self._rst.value = False; time.sleep(0.002)
        self._rst.value = True;  time.sleep(0.012)
        self._wait_busy(500)

        self._cmd(_SET_STANDBY, 0x00)           # STDBY_RC

        self._cmd(_SET_REGULATOR_MODE, 0x00 if useRegulatorLDO else 0x01)

        if tcxoVoltage > 0:
            v = {1.6:0x00, 1.7:0x01, 1.8:0x02, 2.2:0x03,
                 2.4:0x04, 2.7:0x05, 3.0:0x06, 3.3:0x07}.get(tcxoVoltage, 0x02)
            self._cmd(_SET_DIO3_TCXO, v, 0x00, 0x01, 0x40)  # delay ~5 ms
            time.sleep(0.010)

        self._cmd(_CALIBRATE, 0xFF)
        time.sleep(0.020); self._wait_busy(500)

        f1, f2 = _image_cal_bytes(freq)
        self._cmd(_CALIBRATE_IMAGE, f1, f2)
        self._wait_busy(500)

        # LoRa mode
        self._cmd(_SET_PKT_TYPE, 0x01)

        # RF frequency
        frf = round(freq * 1e6 * (1 << 25) / 32_000_000)
        self._cmd(_SET_RF_FREQUENCY,
                  (frf >> 24) & 0xFF, (frf >> 16) & 0xFF,
                  (frf >>  8) & 0xFF,  frf        & 0xFF)

        # PA config — SX1262 high-power path, 22 dBm
        self._cmd(_SET_PA_CONFIG, 0x04, 0x07, 0x00, 0x01)

        pw = max(-17, min(22, int(power)))
        self._cmd(_SET_TX_PARAMS, pw & 0xFF, 0x04)  # ramp 200 us

        self._apply_mod()

        # Packet params: preamble=8, explicit header, max_payload=255, CRC on
        self._cmd(_SET_PKT_PARAMS, 0x00, 0x08, 0x00, 0xFF, 0x01, 0x00)

        # Buffer base addresses (TX@0, RX@0 — half-duplex, never overlap)
        self._cmd(_SET_BUF_BASE_ADDR, 0x00, 0x00)

        self._rx_active = False

    def _apply_mod(self):
        bw_r   = _BW_REG.get(self._bw, 0x04)
        cr_r   = max(1, min(4, self._cr - 4))   # 4/5->1, 4/6->2, 4/7->3, 4/8->4
        sym_ms = (1 << self._sf) / self._bw
        ldro   = 0x01 if sym_ms >= 16.0 else 0x00
        self._cmd(_SET_MOD_PARAMS, self._sf, bw_r, cr_r, ldro)

    # == TX ====================================================================

    def send(self, data, timeout_ms=5000):
        """
        Blocking transmit. Waits for TxDone IRQ.
        Raises RuntimeError on hardware timeout.
        """
        self._rx_active = False
        self._clr_irq()
        self._set_irq(_IRQ_TX_DONE | _IRQ_TIMEOUT)

        self._write(bytearray([_WRITE_BUF, 0x00]) + bytearray(data))
        self._cmd(_SET_PKT_PARAMS, 0x00, 0x08, 0x00, len(data) & 0xFF, 0x01, 0x00)

        self._tx_mode()
        self._cmd(_SET_TX, 0x00, 0x00, 0x00)   # no timeout — TxDone fires when done

        irq = self._poll_irq(_IRQ_TX_DONE | _IRQ_TIMEOUT, timeout_ms)
        self._rx_mode()
        self._clr_irq()

        if not irq or (irq & _IRQ_TIMEOUT):
            raise RuntimeError("SX1262 TX timeout")

    # == RX ====================================================================

    def recv(self, timeout_en=True, timeout_ms=500):
        """
        Blocking receive.
        Returns (data_bytes, 0)  on success
                (None, 0)        on timeout
                (None, 1)        on CRC / header error
        """
        self._clr_irq()
        rx_mask = _IRQ_RX_DONE | _IRQ_TIMEOUT | _IRQ_CRC_ERR | _IRQ_HEADER_ERR
        self._set_irq(rx_mask)

        if timeout_en and timeout_ms > 0:
            t  = min(round(timeout_ms * 1000 / 15.625), 0xFFFFFF)
            tb = [(t >> 16) & 0xFF, (t >> 8) & 0xFF, t & 0xFF]
        else:
            tb = [0xFF, 0xFF, 0xFF]   # continuous

        self._rx_mode()
        self._cmd(_SET_RX, *tb)
        self._rx_active = True

        poll_ms = (timeout_ms + 300) if timeout_en else 120_000
        irq = self._poll_irq(rx_mask, poll_ms)
        self._clr_irq()
        self._rx_active = False

        if not irq or (irq & _IRQ_TIMEOUT):
            return (None, 0)
        if irq & (_IRQ_CRC_ERR | _IRQ_HEADER_ERR):
            return (None, 1)

        bs   = self._cmd_r(_GET_RX_BUF_STATUS, 1, 2)   # [length, offset]
        plen, poff = bs[0], bs[1]
        if plen == 0:
            return (None, 0)

        buf  = bytearray([_READ_BUF, poff, 0x00] + [0x00] * plen)
        resp = self._xfer(buf)
        self._fetch_pkt_status()
        return (bytes(resp[3:]), 0)

    # == Async (non-blocking) RX ===============================================

    def recv_start(self, timeout_ms=0):
        """Enter RX mode and return immediately. Poll with recv_poll()."""
        self._clr_irq()
        rx_mask = _IRQ_RX_DONE | _IRQ_TIMEOUT | _IRQ_CRC_ERR | _IRQ_HEADER_ERR
        self._set_irq(rx_mask)
        if timeout_ms > 0:
            t  = min(round(timeout_ms * 1000 / 15.625), 0xFFFFFF)
            tb = [(t >> 16) & 0xFF, (t >> 8) & 0xFF, t & 0xFF]
        else:
            tb = [0xFF, 0xFF, 0xFF]
        self._rx_mode()
        self._cmd(_SET_RX, *tb)
        self._rx_active = True

    def recv_poll(self):
        """
        Non-blocking poll after recv_start().
        Returns same tuple as recv(), or None if nothing ready yet.
        """
        if not self._rx_active:
            return None
        irq       = self._get_irq()
        done_mask = _IRQ_RX_DONE | _IRQ_TIMEOUT | _IRQ_CRC_ERR | _IRQ_HEADER_ERR
        if not (irq & done_mask):
            return None
        self._clr_irq()
        self._rx_active = False

        if irq & _IRQ_TIMEOUT:
            return (None, 0)
        if irq & (_IRQ_CRC_ERR | _IRQ_HEADER_ERR):
            return (None, 1)

        bs   = self._cmd_r(_GET_RX_BUF_STATUS, 1, 2)
        plen, poff = bs[0], bs[1]
        if plen == 0:
            return (None, 0)

        buf  = bytearray([_READ_BUF, poff, 0x00] + [0x00] * plen)
        resp = self._xfer(buf)
        self._fetch_pkt_status()
        return (bytes(resp[3:]), 0)

    # == Hardware CAD ==========================================================

    def cad(self, timeout_ms=250):
        """
        Hardware Channel Activity Detection.
        Returns True if LoRa preamble activity is detected.
        ~2 x symbol_time to complete: SF7/125kHz ~0.7 ms, SF12 ~66 ms.
        """
        self._clr_irq()
        self._set_irq(_IRQ_CAD_DONE | _IRQ_CAD_DETECTED)

        peak = _CAD_PEAK.get(self._sf, 22)
        # 2 symbols, SF-specific peak threshold, min=10, CAD_ONLY exit
        self._cmd(_SET_CAD_PARAMS, 0x01, peak, 0x0A, 0x00, 0x00, 0x00, 0x00)
        self._rx_mode()
        self._cmd(_SET_CAD)

        irq = self._poll_irq(_IRQ_CAD_DONE, timeout_ms)
        self._clr_irq()
        return bool(irq & _IRQ_CAD_DETECTED)

    # == LBT send ==============================================================

    def send_lbt(self, data, max_tries=5, base_backoff_ms=60, tx_timeout_ms=5000):
        """
        Listen-Before-Talk transmit using hardware CAD.
        Returns True on success, False if channel stays busy after max_tries.
        """
        for attempt in range(max_tries):
            if not self.cad():
                self.send(data, tx_timeout_ms)
                return True
            ms = base_backoff_ms * (2 ** attempt) + random.uniform(0, 40)
            time.sleep(ms / 1000.0)
        return False

    # == RSSI / SNR ============================================================

    def getRSSI(self):
        """RSSI of last received packet (dBm)."""
        return self._last_rssi

    def getSNR(self):
        """SNR of last received packet (dB)."""
        return self._last_snr

    def getRSSIInst(self):
        """Instantaneous channel RSSI (dBm). Useful for quick LBT without CAD."""
        self._cmd(_SET_STANDBY, 0x00)
        r = self._cmd_r(_GET_RSSI_INST, 1, 1)
        return -(r[0] >> 1)

    # == Runtime SF / BW change ================================================

    def set_sf(self, sf):
        """Change spreading factor without full re-init."""
        self._sf = sf
        self._apply_mod()

    def set_freq(self, freq_mhz):
        """Change RF frequency without full re-init."""
        self._freq = freq_mhz
        frf = round(freq_mhz * 1e6 * (1 << 25) / 32_000_000)
        self._cmd(_SET_RF_FREQUENCY,
                  (frf >> 24) & 0xFF, (frf >> 16) & 0xFF,
                  (frf >>  8) & 0xFF,  frf        & 0xFF)
