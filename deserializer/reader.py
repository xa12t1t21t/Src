import struct


class BytecodeReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.size = len(data)

    def remaining(self) -> int:
        return self.size - self.pos

    def has_data(self) -> bool:
        return self.pos < self.size

    def read_byte(self) -> int:
        if self.pos >= self.size:
            raise EOFError(f"Attempted to read byte at position {self.pos}, but only {self.size} bytes available")
        val = self.data[self.pos]
        self.pos += 1
        return val

    def read_bytes(self, n: int) -> bytes:
        if self.pos + n > self.size:
            raise EOFError(f"Attempted to read {n} bytes at position {self.pos}, but only {self.remaining()} bytes remaining")
        val = self.data[self.pos:self.pos + n]
        self.pos += n
        return val

    def read_uint32(self) -> int:
        raw = self.read_bytes(4)
        return struct.unpack("<I", raw)[0]

    def read_int32(self) -> int:
        raw = self.read_bytes(4)
        return struct.unpack("<i", raw)[0]

    def read_float64(self) -> float:
        raw = self.read_bytes(8)
        return struct.unpack("<d", raw)[0]

    def read_float32(self) -> float:
        raw = self.read_bytes(4)
        return struct.unpack("<f", raw)[0]

    def read_varint(self) -> int:
        result = 0
        shift = 0
        while True:
            byte = self.read_byte()
            result |= (byte & 0x7F) << shift
            shift += 7
            if (byte & 0x80) == 0:
                break
        return result

    def read_string(self, length: int) -> str:
        raw = self.read_bytes(length)
        return raw.decode("utf-8", errors="replace")
