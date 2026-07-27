import socket
import threading
import protocol
from engine import GameEngine

HOST = socket.gethostbyname(socket.gethostname())
PORT = 4444

LEGAL_CARDS = {"Mountain", "Forest", "Plains", "Island", "Swamp", "Lightning Bolt", "Shock", 
               "Lava Spike", "Flame Slash", "Searing Spear", "Skullcrack", "Rift Bolt", 
               "Incinerate", "Goblin Guide", "Goblin Bushwhacker", "Reckless Wurm", 
               "Monastery Swiftspear", "Counterspell", "Cancel", "Unsummon", "Ponder", 
               "Negate", "Mana Leak", "Merfolk Looter", "Prodigal Sorcerer", 
               "Air Elemental", "Phantasmal Bear", "Giant Growth", "Rampant Growth", 
               "Naturalize", "Vines of Vastwood", "Llanowar Elves", "Elvish Mystic", 
               "Grizzly Bears", "Leatherback Baloth", "Troll Ascetic", "Wall of Stone", 
               "Swords to Plowshares", "Path to Exile", "Healing Salve", "Pacifism", 
               "White Knight", "Serra Angel", "Savannah Lions", "Mother of Runes", 
               "Dark Ritual", "Terror", "Doom Blade", "Raise Dead", "Mind Rot", 
               "Gray Merchant of Asphodel", "Gravedigger", "Royal Assassin", 
               "Black Knight", "Sol Ring", "Ornithopter", "Millstone", "Rod of Ruin"}

class MTGNPServer:
    def __init__(self):
        self.HOST = HOST
        self.PORT = PORT
        self.clients = []
        self.players = {}
        self.seq_num = 0
        self.phase = "LOBBY"
        self.lock = threading.Lock()
        self.engine = GameEngine(self)

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
            protocol.send_pdu(client, update)

    def handle_client(self, conn, addr):
        print("[server.py]: Connected to", addr)

        while True:
            try:
                pdu = protocol.recv_pdu(conn)
                if not pdu:
                    break
                
                with self.lock:
                    if self.phase == "LOBBY":
                        if pdu['type'] == "PLAYER_READY":
                            pid = pdu.get('player_id')
                            deck = pdu.get('deck_list', [])
                            
                            if not pid:
                                continue  # Ignore if player_id is not provided
                            
                            if pid in self.players and self.players[pid]['sock'] != conn:
                                error = {
                                    "type": "ERROR",
                                    "seq_num": self.get_next_seq_num(),
                                    "code": "DUPLICATE_ID",
                                    "message": f"Player ID '{pid}' is already taken.",
                                    "rejected_action": pdu
                                }
                                protocol.send_pdu(conn, error)
                                continue

                            # Step 1: Validation
                            invalid_cards = [card for card in deck if card not in LEGAL_CARDS]
                            if not (1 <= len(deck) <= 50) or invalid_cards:
                                error = {
                                    "type": "ERROR",
                                    "seq_num": self.get_next_seq_num(),
                                    "code": "ILLEGAL_DECK",
                                    "message": "Invalid deck size, or contains illegal cards.",
                                    "rejected_action": pdu
                                }
                                protocol.send_pdu(conn, error)
                                continue

                            # Step 2: Registration
                            print(f"[server.py]: Player '{pid}' is ready!")
                            self.players[pid] = {"deck": deck, "sock": conn}

                            # Step 3: Respond status
                            self.broadcast_status()

                            # Step 4: Check if GAME_SETUP can proceed
                            if len(self.players) == 2:
                                print("[server.py]: Both players are ready. Moving to GAME_SETUP...")
                                self.phase = "GAME_SETUP"
                                # Implement section 6.3
                                self.engine.start_game_setup()
                    else:
                        pid = self.get_player_id_by_socket(conn)
                        if pid:
                            self.engine.handle_pdu(pid, pdu)
                            
            except Exception as e:
                print("[server.py]: Error: ", e)
                break

        print("[server.py]: Closing connection")
        conn.close()
        
    def get_player_id_by_socket(self, sock):
        for pid, info in self.players.items():
            if info['sock'] == sock:
                return pid
        return None
    
    def send_to_player(self, player_id, pdu):
        if player_id in self.players:
            protocol.send_pdu(self.players[player_id]['sock'], pdu)
    
    def get_next_seq_num(self):
        self.seq_num += 1
        return self.seq_num

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