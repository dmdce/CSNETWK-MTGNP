import json
import struct
from client import MAX_PDU_SIZE

def send_pdu(sock, pdu):
    # Frame JSON PDU with 4-byte big-endian length prefix
    payload = json.dumps(pdu).encode('utf-8')

    if len(payload) > MAX_PDU_SIZE:
        raise ValueError(f"[protocol]: PDU payload of {len(payload)} bytes exceeds max PDU size")

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
            raise ConnectionError('[protocol]: Socket closed prematurely')
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
        raise ValueError(f"[protocol]: Incoming PDU declared length {length} bytes exceeds max PDU size")

    body = _recv_exact(sock, length)
    if body is None:
        return None

    return json.loads(body.decode('utf-8'))