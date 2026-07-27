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
            "stack": [],
            "battlefield": {p1: [], p2: []},
            "graveyard": {p1: [], p2: []},
            "hand": {p1: hand_p1, p2: hand_p2},
            "hand_counts": {p1: 7, p2: 7},
            "libraries": {p1: deck_p1, p2: deck_p2},
            "land_played_this_turn": False
        }
        
        self.mulligan_choices = {}
        self.mulligan_counts = {p1: 0, p2: 0}
        
        self.send_personalized_game_state()
        self.server.phase = "MULLIGAN"
        
        
    def send_personalized_game_state(self, target_player=None):
        seq_num = self.server.get_next_sequence_number()
        p1, p2 = self.player_ids[0], self.player_ids[1]
        
        targets = [target_player] if target_player else self.player_ids
        
        for p in targets:
            opponent = p2 if p == p1 else p1
            
            visible_state = {
                "turn": self.state["turn"],
                "phase": self.state["phase"],
                "active_player": self.state["active_player"],
                "life_totals": copy.deepcopy(self.state["life_totals"]),
                "hand": copy.deepcopy(self.state["hand"][p]),
                "hand_counts": {opponent: self.state["hand_counts"][opponent]},
                "libraries": {p1: self.state["libraries"][p1], 
                                   p2: self.state["libraries"][p2]},
                "battlefield": copy.deepcopy(self.state["battlefield"]),
                "graveyard": copy.deepcopy(self.state["graveyard"]),
                "stack": copy.deepcopy(self.state["stack"])
            }
            
            if "priority_holder" in self.state and self.state["priority_holder"] is not None:
                visible_state["priority_holder"] = self.state["priority_holder"]
                
            if "land_played_this_turn" in self.state:
                visible_state["land_played_this_turn"] = self.state["land_played_this_turn"]
                
            pdu = {
                "type": "GAME_STATE_UPDATE",
                "seq_num": seq_num,
                "state": visible_state
            }
            self.server.send_pdu(p, pdu)
            
        
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
                
                    
    def handle_mulligan(self, player_id, pdu):
        keep = pdu.get("keep", True)
        
        if keep:
            expected_bottom = self.mulligan_counts[player_id]
            cards_to_bottom = pdu.get("cards_to_bottom", [])
            
            if len(cards_to_bottom) != expected_bottom:
                self.server.send_pdu(player_id, {
                    "type": "ERROR",
                    "seq_num": self.server.get_next_sequence_number(),
                    "code": "ILLEGAL_ACTION",
                    "message": f"Expected to bottom {expected_bottom} cards, but got {len(cards_to_bottom)}.",
                    "rejected_action": pdu
                })
                return
            
            hand = self.state["hand"][player_id]
            # Verify that the cards to bottom are actually in the player's hand
            temp_hand = list(hand)
        
            try:
                for c in cards_to_bottom:
                    temp_hand.remove(c)
            except ValueError:
                self.server.send_to_player(player_id, {
                    "type": "ERROR",
                    "seq_num": self.server.get_next_sequence_number(),
                    "code": "ILLEGAL_ACTION",
                    "message": f"One or more cards to bottom are not in the player's hand.",
                    "rejected_action": pdu
                })
                return
        
            self.state["hand"][player_id] = temp_hand
            self.state["libraries"][player_id].extend(cards_to_bottom)
            
            self.mulligan_choices[player_id] = True
            
            if len(self.mulligan_choices) == 2 and all(self.mulligan_choices.values()):
                self.transition_to_game()
        else:
            self.mulligan_counts[player_id] += 1
            
            hand = self.state["hand"][player_id]
            library = self.state["libraries"][player_id]
            library.extend(hand)
            random.shuffle(library)
            
            self.state["hand"][player_id] = library[:7]
            self.state["libraries"][player_id] = library[7:]
            
            self.send_personalized_game_state(target_player=player_id)
            
    def transition_to_game(self):
        # TODO: Implement transition to game logic here
        print("cool")
        
            
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