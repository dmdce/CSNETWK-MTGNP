import json
import struct

def send_pdu(sock, pdu):
    # Frame JSON PDU with 4-byte big-endian length prefix
    payload = json.dumps(pdu).encode('utf-8')
    header = struct.pack('>I', len(payload))
    sock.sendall(header + payload)

def recv_pdu(sock):
    # Reads amount of bytes in 4-byte prefix
    header = sock.recv(4)
    if not header:
        return None

    length = struct.unpack('>I', header)[0]
    chunks = []
    bytes_recd = 0

    while bytes_recd < length:
        chunk = sock.recv(min(4096, length - bytes_recd))
        if not chunk:
            raise ConnectionError('[utils.py]: Socket closed prematurely')
        chunks.append(chunk)
        bytes_recd += len(chunk)

    return json.loads(b''.join(chunks).decode('utf-8'))