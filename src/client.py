import struct
import sys
import socket
import json

HOST = socket.gethostbyname(socket.gethostname())
PORT = 6700

def send_pdu(client, pdu):
    # Frame JSON PDU with 4-byte big-endian length prefix
    payload = json.dumps(pdu).encode('utf-8')
    header = struct.pack('>I', len(payload))
    client.sendall(header + payload)

def recv_pdu(client):
    # Reads amount of bytes in 4-byte prefix
    header = client.recv(4)
    if not header:
        return None

    length = struct.unpack('>I', header)[0]
    chunks = []
    bytes_recd = 0

    while bytes_recd < length:
        chunk = client.recv(min(4096, length - bytes_recd))
        if not chunk:
            raise ConnectionError('Socket closed prematurely')
        chunks.append(chunk)
        bytes_recd += len(chunk)

    return json.loads(b''.join(chunks).decode('utf-8'))

def start_client(player_id):
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((HOST, PORT))

        print("+ Connected to server as", player_id)

        # Send PLAYER_READY
        ready_pdu = {
            "type": "PLAYER_READY",
            "seq_num": 1,
            "player_id": player_id,
            "deck_list": []
        }

        send_pdu(client, ready_pdu)


    except ConnectionRefusedError:
        print("+ Connection refused")
    except Exception as e:
        print("+ Client error:", e)
    finally:
        print("+ Closing connection")
        client.close()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        player = sys.argv[1]
    else:
        player = "anonymous"
    start_client(player)