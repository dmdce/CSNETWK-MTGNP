import struct
import sys
import socket
import utils

HOST = socket.gethostbyname(socket.gethostname())
PORT = 6700

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

        utils.send_pdu(client, ready_pdu)


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