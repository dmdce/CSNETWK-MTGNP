import socket
import threading
import utils

HOST = socket.gethostbyname(socket.gethostname())
PORT = 6700

class MTGNPServer:
    def __init__(self):
        self.HOST = HOST
        self.PORT = PORT
        self.clients = []
        self.players = {}
        self.seq_num = 0
        self.phase = "LOBBY"

    def broadcast_status(self):
        count_ready = len(self.players)
        waiting_for = ["player_2"] if count_ready == 1 else []

        self.seq_num += 1

        update = {
            "type": "GAME_STATE_UPDATE",
            "seq_num": self.seq_num,
            "state": {
                "phase": "LOBBY",
                "players_ready": count_ready,
                "waiting_for": waiting_for
            }
        }

        for client, _ in self.clients:
            utils.send_pdu(client, update)

    def handle_client(self, conn, addr):
        print("[server.py]: Connected to", addr)

        while True:
            try:
                pdu = utils.recv_pdu(conn)
                if not pdu:
                    break

                if pdu['type'] == "PLAYER_READY":
                    pid = pdu.get('player_id')
                    deck = pdu.get('deck_list', [])

                    # Step 1: Validation
                    if not (1 <= len(deck) <= 50):
                        error = {
                            "type": "ERROR",
                            "code": "ILLEGAL_DECK",
                            "message": "Invalid deck size, 1-50 cards only"
                        }
                        utils.send_pdu(conn, error)
                        continue

                    # Step 2: Registration
                    print(f"[server.py]: Player '{pid}' is ready!")
                    self.players[pid] = {"deck": deck, "sock": conn}

                    # Step 3: Respond status
                    self.broadcast_status()

                    # Step 4: Check if GAME_SETUP can proceed
            except Exception as e:
                print("[server.py]: Error: ", e)
                break

        print("[server.py]: Closing connection")
        conn.close()

    def start(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((self.HOST, self.PORT))
        server.listen(2)

        print(f"[server.py]: Listening on {self.HOST}:{self.PORT}. ~LOBBY Phase~")

        while len(self.clients) < 2:
            conn, addr = server.accept()
            self.clients.append((conn, addr))
            threading.Thread(target=self.handle_client, args=(conn, addr)).start()

        while True:
            pass

if __name__ == "__main__":
    server = MTGNPServer()
    server.start()