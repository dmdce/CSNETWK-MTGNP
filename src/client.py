import struct
import sys
import socket
import utils

HOST = socket.gethostbyname(socket.gethostname())
PORT = 4444

def start_client(player_id):
    print("[client.py]: Starting", player_id)

    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((HOST, PORT))

        print("[client.py]: Connected to server as", player_id)

        # Send PLAYER_READY
        ready_pdu = {
            "type": "PLAYER_READY",
            "seq_num": 1,
            "player_id": player_id,
            "deck_list": []
        }

        utils.send_pdu(client, ready_pdu)

        # Receive PDU
        while True:
            response = utils.recv_pdu(client)
            if response:
                print("[client.py]: Received server PDU:", response)
                print(f"Type: {response['type']}")
                if 'state' in response:
                    state = response['state']
                    print(f"Phase: {state['phase']} | Players Ready: {state['players_ready']}")
                if response.get('type') == "ERROR":
                    print(f"ERROR: {response['message']}")
    except ConnectionRefusedError:
        print("[client.py]: Connection refused")
    except Exception as e:
        print("[client.py]: Client error:", e)
    finally:
        print("[client.py]: Closing connection")
        client.close()

if __name__ == '__main__':
    if len(sys.argv) > 1:
        player = sys.argv[1]
    else:
        player = "anonymous"
    start_client(player)