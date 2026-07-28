import socket
import threading
from protocol import send_pdu, recv_pdu
from engine import GameEngine

HOST = socket.gethostbyname(socket.gethostname())
PORT = 4444

# LEGAL_CARDS = {"Mountain", "Forest", "Plains", "Island", "Swamp", "Lightning Bolt", "Shock", 
#                "Lava Spike", "Flame Slash", "Searing Spear", "Skullcrack", "Rift Bolt", 
#                "Incinerate", "Goblin Guide", "Goblin Bushwhacker", "Reckless Wurm", 
#                "Monastery Swiftspear", "Counterspell", "Cancel", "Unsummon", "Ponder", 
#                "Negate", "Mana Leak", "Merfolk Looter", "Prodigal Sorcerer", 
#                "Air Elemental", "Phantasmal Bear", "Giant Growth", "Rampant Growth", 
#                "Naturalize", "Vines of Vastwood", "Llanowar Elves", "Elvish Mystic", 
#                "Grizzly Bears", "Leatherback Baloth", "Troll Ascetic", "Wall of Stone", 
#                "Swords to Plowshares", "Path to Exile", "Healing Salve", "Pacifism", 
#                "White Knight", "Serra Angel", "Savannah Lions", "Mother of Runes", 
#                "Dark Ritual", "Terror", "Doom Blade", "Raise Dead", "Mind Rot", 
#                "Gray Merchant of Asphodel", "Gravedigger", "Royal Assassin", 
#                "Black Knight", "Sol Ring", "Ornithopter", "Millstone", "Rod of Ruin"}
LEGAL_CARDS = {
    "lightning_bolt_001", "lightning_bolt_002", "lightning_bolt_003", "lightning_bolt_004",
    "shock_001", "shock_002", "shock_003", "shock_004",
    "lava_spike_001", "lava_spike_002", "lava_spike_003", "lava_spike_004",
    "flame_slash_001", "flame_slash_002", "flame_slash_003", "flame_slash_004",
    "searing_spear_001", "searing_spear_002", "searing_spear_003", "searing_spear_004",
    "skullcrack_001", "skullcrack_002", "skullcrack_003", "skullcrack_004",
    "rift_bolt_001", "rift_bolt_002", "rift_bolt_003", "rift_bolt_004",
    "incinerate_001", "incinerate_002", "incinerate_003", "incinerate_004",
    "goblin_guide_001", "goblin_guide_002", "goblin_guide_003", "goblin_guide_004",
    "goblin_bushwhacker_001", "goblin_bushwhacker_002", "goblin_bushwhacker_003", "goblin_bushwhacker_004",
    "reckless_wurm_001", "reckless_wurm_002", "reckless_wurm_003", "reckless_wurm_004",
    "monastery_swiftspear_001", "monastery_swiftspear_002", "monastery_swiftspear_003", "monastery_swiftspear_004",
    "counterspell_001", "counterspell_002", "counterspell_003", "counterspell_004",
    "cancel_001", "cancel_002", "cancel_003", "cancel_004",
    "unsummon_001", "unsummon_002", "unsummon_003", "unsummon_004",
    "ponder_001", "ponder_002", "ponder_003", "ponder_004",
    "negate_001", "negate_002", "negate_003", "negate_004",
    "mana_leak_001", "mana_leak_002", "mana_leak_003", "mana_leak_004",
    "merfolk_looter_001", "merfolk_looter_002", "merfolk_looter_003", "merfolk_looter_004",
    "prodigal_sorcerer_001", "prodigal_sorcerer_002", "prodigal_sorcerer_003", "prodigal_sorcerer_004",
    "air_elemental_001", "air_elemental_002", "air_elemental_003", "air_elemental_004",
    "phantasmal_bear_001", "phantasmal_bear_002", "phantasmal_bear_003", "phantasmal_bear_004",
    "giant_growth_001", "giant_growth_002", "giant_growth_003", "giant_growth_004",
    "rampant_growth_001", "rampant_growth_002", "rampant_growth_003", "rampant_growth_004",
    "naturalize_001", "naturalize_002", "naturalize_003", "naturalize_004",
    "vines_of_vastwood_001", "vines_of_vastwood_002", "vines_of_vastwood_003", "vines_of_vastwood_004",
    "llanowar_elves_001", "llanowar_elves_002", "llanowar_elves_003", "llanowar_elves_004",
    "elvish_mystic_001", "elvish_mystic_002", "elvish_mystic_003", "elvish_mystic_004",
    "grizzly_bears_001", "grizzly_bears_002", "grizzly_bears_003", "grizzly_bears_004",
    "leatherback_baloth_001", "leatherback_baloth_002", "leatherback_baloth_003", "leatherback_baloth_004",
    "troll_ascetic_001", "troll_ascetic_002", "troll_ascetic_003", "troll_ascetic_004",
    "wall_of_stone_001", "wall_of_stone_002", "wall_of_stone_003", "wall_of_stone_004",
    "swords_to_plowshares_001", "swords_to_plowshares_002", "swords_to_plowshares_003", "swords_to_plowshares_004",
    "path_to_exile_001", "path_to_exile_002", "path_to_exile_003", "path_to_exile_004",
    "healing_salve_001", "healing_salve_002", "healing_salve_003", "healing_salve_004",
    "pacifism_001", "pacifism_002", "pacifism_003", "pacifism_004",
    "white_knight_001", "white_knight_002", "white_knight_003", "white_knight_004",
    "serra_angel_001", "serra_angel_002", "serra_angel_003", "serra_angel_004",
    "savannah_lions_001", "savannah_lions_002", "savannah_lions_003", "savannah_lions_004",
    "mother_of_runes_001", "mother_of_runes_002", "mother_of_runes_003", "mother_of_runes_004",
    "dark_ritual_001", "dark_ritual_002", "dark_ritual_003", "dark_ritual_004",
    "terror_001", "terror_002", "terror_003", "terror_004",
    "doom_blade_001", "doom_blade_002", "doom_blade_003", "doom_blade_004",
    "raise_dead_001", "raise_dead_002", "raise_dead_003", "raise_dead_004",
    "mind_rot_001", "mind_rot_002", "mind_rot_003", "mind_rot_004",
    "gray_merchant_001", "gray_merchant_002", "gray_merchant_003", "gray_merchant_004",
    "gravedigger_001", "gravedigger_002", "gravedigger_003", "gravedigger_004",
    "royal_assassin_001", "royal_assassin_002", "royal_assassin_003", "royal_assassin_004",
    "black_knight_001", "black_knight_002", "black_knight_003", "black_knight_004",
    "sol_ring_001", "sol_ring_002", "sol_ring_003", "sol_ring_004",
    "ornithopter_001", "ornithopter_002", "ornithopter_003", "ornithopter_004",
    "millstone_001", "millstone_002", "millstone_003", "millstone_004",
    "rod_of_ruin_001", "rod_of_ruin_002", "rod_of_ruin_003", "rod_of_ruin_004",
    "mountain_001", "mountain_002", "mountain_003", "mountain_004", "mountain_005", "mountain_006", "mountain_007", "mountain_008", "mountain_009", "mountain_010", "mountain_011", "mountain_012", "mountain_013", "mountain_014", "mountain_015", "mountain_016", "mountain_017", "mountain_018", "mountain_019", "mountain_020",
    "forest_001", "forest_002", "forest_003", "forest_004", "forest_005", "forest_006", "forest_007", "forest_008", "forest_009", "forest_010", "forest_011", "forest_012", "forest_013", "forest_014", "forest_015", "forest_016", "forest_017", "forest_018", "forest_019", "forest_020",
    "plains_001", "plains_002", "plains_003", "plains_004", "plains_005", "plains_006", "plains_007", "plains_008", "plains_009", "plains_010", "plains_011", "plains_012", "plains_013", "plains_014", "plains_015", "plains_016", "plains_017", "plains_018", "plains_019", "plains_020",
    "island_001", "island_002", "island_003", "island_004", "island_005", "island_006", "island_007", "island_008", "island_009", "island_010", "island_011", "island_012", "island_013", "island_014", "island_015", "island_016", "island_017", "island_018", "island_019", "island_020",
    "swamp_001", "swamp_002", "swamp_003", "swamp_004", "swamp_005", "swamp_006", "swamp_007", "swamp_008", "swamp_009", "swamp_010", "swamp_011", "swamp_012", "swamp_013", "swamp_014", "swamp_015", "swamp_016", "swamp_017", "swamp_018", "swamp_019", "swamp_020",
}

class MTGNPServer:
    def __init__(self):
        self.host = HOST
        self.port = PORT
        self.clients = []
        self.players = {}
        self.max_players = 2
        self.seq_num = 0
        self.phase = "LOBBY"
        self.game_active = True
        self.lock = threading.Lock()
        self.engine = GameEngine(self)

    def handle_disconnect(self, player_id):
        if player_id not in self.players or self.players[player_id]['status'] == 'DISCONNECTED':
            return

        print(f"[server] Player {player_id} disconnected. Starting {10}s timer...")
        self.players[player_id]['status'] = 'DISCONNECTED'

        # Start the reconnect timer
        timer = threading.Timer(10, self.on_reconnect_timeout, [player_id])
        self.players[player_id]['timer'] = timer
        timer.start()

    def on_reconnect_timeout(self, player_id):
        if self.players[player_id]['status'] == 'DISCONNECTED':
            print(f"[server] FAILURE: {player_id} failed to reconnect. Ending game.")
            self.broadcast_game_over(loser_id = player_id, reason = "DISCONNECT")

    def broadcast_game_over(self, loser_id, reason):
        self.game_active = False
        # Determine winner (one who didn't disconnect)
        winner_id = next(pid for pid in self.players if pid != loser_id)

        pdu = {
            "type": "GAME_OVER",
            "seq_num": 999,
            "winner_id": winner_id,
            "loser_id": loser_id,
            "reason": reason
        }

        for pid, data in self.players.items():
            if data['status'] == 'CONNECTED':
                try:
                    send_pdu(data['sock'], pdu)
                except:
                    pass

        print("[server] Resetting server state to LOBBY phase...")
        self.phase = "LOBBY"
        self.players = {}
        self.seq_num = 0
        self.broadcast_lobby_status()

    def handle_client_reconnect(self, new_sock, player_id):
        if player_id in self.players and self.players[player_id]['status'] == 'DISCONNECTED':
            print(f"[server] Player {player_id} has reconnected! Cancelling the timeout.")

            # Cancel the timeout timer
            if self.players[player_id]['timer']:
                self.players[player_id]['timer'].cancel()

            self.players[player_id]['sock'] = new_sock
            self.players[player_id]['status'] = 'CONNECTED'
            self.players[player_id]['timer'] = None
            return True
        return False

    def broadcast_lobby_status(self):
        count_ready = len(self.players)
        waiting_for = ["player_2"] if count_ready == 1 else []

        update = {
            "type": "GAME_STATE_UPDATE",
            "seq_num": self.get_next_seq_num(),
            "state": {
                "phase": "LOBBY",
                "players_ready": count_ready,
                "waiting_for": waiting_for
            }
        }

        for client, _ in self.clients:
            send_pdu(client, update)
            
    def reset_lobby_state(self):
        self.players = {}
        self.phase = "LOBBY"
        self.engine.reset_state()
        self.broadcast_lobby_status()

    def handle_client(self, conn, addr):
        pid = None

        print("[server]: Connected to", addr)

        while True:
            try:
                pdu = recv_pdu(conn)
                if not pdu:
                    break

                p_type = pdu.get("type")

                if p_type == "PING":
                    pong_pdu = {
                        "type": "PONG",
                        "seq_num": pdu.get("seq_num"),
                        "timestamp": pdu.get("timestamp")
                    }
                    send_pdu(conn, pong_pdu)
                    continue
                
                with self.lock:
                    if self.phase == "LOBBY":
                        if p_type == "PLAYER_READY":
                            new_pid = pdu.get('player_id')
                            deck = pdu.get('deck_list', [])

                            # Check if pid is RECONNECT or DUPLICATE
                            if new_pid in self.players:
                                existing_player = self.players[new_pid]

                                if existing_player.get('status') == 'CONNECTED':
                                    error = {
                                        "type": "ERROR",
                                        "seq_num": self.get_next_seq_num(),
                                        "code": "DUPLICATE_ID",
                                        "message": f"Player ID '{new_pid}' is already taken.",
                                        "rejected_action": pdu
                                    }
                                    send_pdu(conn, error)
                                    continue
                                else:
                                    # Reconnect logic: Cancel their timeout timer
                                    print(f"[server]: Player {new_pid} reconnected.")
                                    if existing_player.get('timer'):
                                        existing_player['timer'].cancel()

                            # Step 1: Validation
                            if not new_pid:
                                error = {
                                    "type": "ERROR",
                                    "seq_num": self.get_next_seq_num(),
                                    "code": "ILLEGAL_ACTION",
                                    "message": "player_id must be a non-empty string.",
                                    "rejected_action": pdu
                                }
                                send_pdu(conn, error)
                                continue

                            invalid_cards = [card for card in deck if card not in LEGAL_CARDS]
                            if not (1 <= len(deck) <= 50) or invalid_cards:
                                error = {
                                    "type": "ERROR",
                                    "seq_num": self.get_next_seq_num(),
                                    "code": "ILLEGAL_DECK",
                                    "message": "Invalid deck size, or contains illegal cards.",
                                    "rejected_action": pdu
                                }
                                send_pdu(conn, error)
                                continue

                            # Step 2: Registration
                            pid = new_pid
                            print(f"[server]: Player '{pid}' is ready!")
                            self.players[pid] = {
                                "deck": deck,
                                "sock": conn,
                                "status": "CONNECTED",
                                "timer": None
                            }

                            # Step 3: Respond status
                            self.broadcast_lobby_status()

                            # Step 4: Check if GAME_SETUP can proceed
                            if len(self.players) == 2:
                                print("[server]: Both players are ready. Moving to GAME_SETUP...")
                                self.phase = "GAME_SETUP"
                                self.engine.start_game_setup()


                            pid = new_pid
                            deck = pdu.get('deck_list', [])
                            self.players[pid] = {
                                "deck": deck,
                                "sock": conn,
                                "status": "CONNECTED",
                                "timer": None
                            }
                            self.broadcast_lobby_status()

                            if len(self.players) == 2:
                                self.phase = "GAME_SETUP"
                                self.engine.start_game_setup()
                    elif self.phase == "GAME_OVER":
                        continue
                    else:
                        current_pid = self.get_player_id_by_socket(conn)
                        if current_pid:
                            self.engine.handle_pdu(pid, pdu)
                            
            except Exception:
                if pid:
                    self.handle_disconnect(pid)
                break
        
        with self.lock:
            if self.phase not in ["LOBBY", "GAME_OVER"]:
                pid = self.get_player_id_by_socket(conn)
                if pid:
                    print(f"[server]: Player {pid} disconnected during game.")
                    self.engine.game_over(loser_id=pid, reason="DISCONNECT")

        if pid:
            self.handle_disconnect(pid)

        print(f"[server]: Closing connection for {addr}...")
        conn.close()
        
    def get_player_id_by_socket(self, sock):
        for pid, info in self.players.items():
            if info['sock'] == sock:
                return pid
        return None
    
    def send_to_player(self, player_id, pdu):
        if player_id in self.players:
            send_pdu(self.players[player_id]['sock'], pdu)
    
    def get_next_seq_num(self):
        self.seq_num += 1
        return self.seq_num

    def start(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(5) # Backlog

        print(f"[server]: Listening on {self.host}:{self.port}...")

        while True:
            conn, addr = server.accept()

            # Count players who are currently 'CONNECTED'
            active_players = [player for player in self.players.values() if player['status'] == 'CONNECTED']

            if len(active_players) >= self.max_players:
                print(f"[server] ERROR: Connection attempt from {addr} refused: Game is full.")
                try:
                    error_pdu = {
                        "type": "ERROR",
                        "code": "ROOM_FULL",
                        "message": "Two players are already connected. Please try again later."
                    }
                    send_pdu(conn, error_pdu)
                    conn.close()
                except:
                    pass
                continue

            # If room is available, handle client
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    server = MTGNPServer()
    server.start()