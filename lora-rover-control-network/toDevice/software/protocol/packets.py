# SPDX-License-Identifier: MIT

"""ASCII H/R/D packet codec compatible with the cleanup-sf7 mesh branch."""


class PacketDecodeError(ValueError):
    pass


class HelloPacket:
    def __init__(self, src):
        self.src = int(src)


class RouteAdPacket:
    def __init__(self, orig, fwd, mid, hops, path_rssi=None, path_snr=None):
        self.orig = int(orig)
        self.fwd = int(fwd)
        self.mid = int(mid) & 0xFF
        self.hops = int(hops)
        self.path_rssi = int(path_rssi) if path_rssi is not None else None
        self.path_snr = float(path_snr) if path_snr is not None else None


class DataPacket:
    def __init__(self, src, dst, next_hop, mid, ttl, payload):
        self.src = int(src)
        self.dst = int(dst)
        self.next_hop = int(next_hop)
        self.mid = int(mid) & 0xFF
        self.ttl = int(ttl)
        self.payload = str(payload)


class PacketCodec:
    def encode_hello(self, src):
        return "H:{0}".format(int(src)).encode("utf-8")

    def encode_route_ad(self, orig, fwd, mid, hops, path_rssi=None, path_snr=None):
        base = "R:{0}:{1}:{2}:{3}".format(
            int(orig), int(fwd), int(mid) & 0xFF, int(hops)
        )
        if path_rssi is not None:
            base += ":{0}:{1:.1f}".format(int(path_rssi), float(path_snr or 0.0))
        return base.encode("utf-8")

    def encode_data(self, src, dst, next_hop, mid, ttl, payload):
        return "D:{0}:{1}:{2}:{3}:{4}:{5}".format(
            int(src),
            int(dst),
            int(next_hop),
            int(mid) & 0xFF,
            int(ttl),
            str(payload),
        ).encode("utf-8")

    def decode(self, raw):
        if raw is None:
            return None
        if isinstance(raw, str):
            text = raw.strip()
        else:
            try:
                text = bytes(raw).decode("utf-8", "ignore").strip()
            except Exception as exc:
                raise PacketDecodeError("packet is not text") from exc
        if not text:
            return None
        if text.startswith("H:"):
            return self.decode_hello_text(text)
        if text.startswith("R:"):
            return self.decode_route_ad_text(text)
        if text.startswith("D:"):
            return self.decode_data_text(text)
        return None

    def decode_hello_text(self, text):
        parts = text[2:].split(":")
        if len(parts) != 1:
            raise PacketDecodeError("invalid HELLO")
        return HelloPacket(int(parts[0]))

    def decode_route_ad_text(self, text):
        parts = text[2:].split(":")
        if len(parts) not in (4, 6):
            raise PacketDecodeError("invalid ROUTE_AD")
        path_rssi = int(parts[4]) if len(parts) == 6 else None
        path_snr = float(parts[5]) if len(parts) == 6 else None
        return RouteAdPacket(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]),
                             path_rssi=path_rssi, path_snr=path_snr)

    def decode_data_text(self, text):
        parts = text[2:].split(":", 5)
        if len(parts) != 6:
            raise PacketDecodeError("invalid DATA")
        return DataPacket(
            int(parts[0]),
            int(parts[1]),
            int(parts[2]),
            int(parts[3]),
            int(parts[4]),
            parts[5],
        )
