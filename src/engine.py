import copy
import random

class GameEngine:
    def __init__(self, server):
        self.server = server
        self.state = {}
        self.player_ids = []
        self.mulligan_choices = {}
        self.mulligan_counts = {}

    def start_game_setup(self):
        self.state = "running"
        print("Game started.")
        self.player_ids = list(self.server.players.keys())
        p1, p2 = self.player_ids[0], self.player_ids[1]
        
    
        deck_p1 = copy.deepcopy(self.server.players[p1].deck)
        deck_p2 = copy.deepcopy(self.server.players[p2].deck)
        
        random.shuffle(deck_p1)
        random.shuffle(deck_p2)
        
        hand_p1 = [deck_p1.pop() for _ in range(7)]
        hand_p2 = [deck_p2.pop() for _ in range(7)]
        
        first_player = random.choice([p1, p2])
        
        self.state = {
            turn: 0,
            "phase": "MULLIGAN",
            "active_player": first_player,
            "priority_holder": None,
            "life_totals": {p1: 20, p2: 20},
            "stacks": [],
            "battlefield": {p1: [], p2: []},
            "graveyards": {p1: [], p2: []},
            "hand": {p1: hand_p1, p2: hand_p2},
            "hand_counts": {p1: 7, p2: 7},
            "library_counts": {p1: 0, p2: 0},
            "land_played_this_turn": False
        }
        
        self.mulligan_choices = {}
        self.mulligan_counts = {p1: 0, p2: 0}
        
        self.send_personalized_game_state()
        self.server.phase = "MULLIGAN"
        
        
    def send_personalized_game_state(self, target_player=None):
        seq_num = self.server.get_next_sequence_number()
        
        print(f"Broadcasting state to players: {self.state}")
        
    def handle_pdu(self, player_id, pdu):
        pdu_type = pdu.get("type")
        
        if self.server.phase == "MULLIGAN":
            if pdu_type == "MULLIGAN_CHOICE":
                self.handle_mulligan(player_id, pdu)
        elif self.server.phase == "IN_GAME":
            print(f"[engine.py] Received IN_GAME action from player {player_id}: {pdu_type}")
            match pdu_type:
                case "PRIORITY_PASS":
                    self.handle_priority_pass(player_id)
                case "CAST_SPELL":
                    self.handle_cast_spell(player_id)
                case "PLAY_LAND":
                    self.handle_play_land(player_id)
                case "DISCARD":
                    self.handle_discard(player_id)
                case "CONCEDE":
                    self.game_over(loser_id=player_id, reason="CONCEDE")
                
                    
    def handle_mulligan(self, player_id, choice):
        # TODO: Implement mulligan logic here
        self.send_personalized_game_state()
            
    def handle_priority_pass(self, player_id):
        # TODO: Implement priority pass logic here
        self.send_personalized_game_state()
            
    def handle_cast_spell(self, player_id):
        # TODO: Implement spell casting logic here
        self.send_personalized_game_state()
    
    def handle_play_land(self, player_id):
        # TODO: Implement land playing logic here
        self.send_personalized_game_state()
    
    def handle_discard(self, player_id):
        # TODO: Implement discard logic here
        self.send_personalized_game_state()
    
    def game_over(self, loser_id, reason):
        # TODO: Implement game over logic here
        self.send_personalized_game_state()

    def stop(self):
        self.state = "stopped"
        print("Game stopped.")

    def update(self):
        if self.state == "running":
            print("Game is updating...")
        else:
            print("Game is not running.")