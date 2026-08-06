import json
import struct
from logger import log_pdu

MAX_PDU_SIZE = 65535

class InvalidPduError(Exception):
    # Raised when received bytes cannot be decoded as UTF-8 or parsed as JSON
    pass

def send_pdu(sock, pdu, filename="server_stream.jsonl"):
    """Serializes a PDU, logs it, and sends it with a 4-byte length prefix."""
    # 1. Log outgoing PDU
    log_pdu(pdu, direction="SENT", filename=filename)

    # 2. Serialize and Frame
    payload = json.dumps(pdu).encode('utf-8')

    if len(payload) > MAX_PDU_SIZE:
        raise ValueError(f"[protocol] PDU payload of {len(payload)} bytes exceeds max PDU size")

    header = struct.pack('>I', len(payload))
    sock.sendall(header + payload)

def _recv_exact(sock, num_bytes):
    chunks = []
    bytes_recd = 0

    while bytes_recd < num_bytes:
        chunk = sock.recv(min(4096, num_bytes - bytes_recd))
        if not chunk:
            if bytes_recd == 0:
                return None
            raise ConnectionError('[protocol] Socket closed prematurely')
        chunks.append(chunk)
        bytes_recd += len(chunk)

    return b''.join(chunks)

def recv_pdu(sock):
    # Reads amount of bytes in 4-byte prefix
    header = _recv_exact(sock, 4)
    if header is None:
        return None

    length = struct.unpack('>I', header)[0]

    if length > MAX_PDU_SIZE:
        raise ValueError(f"[protocol] Incoming PDU declared length {length} bytes exceeds max PDU size")

    body = _recv_exact(sock, length)
    if body is None:
        return None

    try:
        text = body.decode('utf-8')
    except UnicodeDecodeError as e:
        raise InvalidPduError(f"[protocol] ERROR: Payload is not valid UTF-8: {e}") from e

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise InvalidPduError(f"[protocol] ERROR: Payload is not valid JSON: {e}") from e