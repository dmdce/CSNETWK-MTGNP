import copy
import random

class GameEngine:
    def __init__(self, server):
        self.server = server
        self.state = {}
        self.player_ids = []
        self.mulligan_choices = {}
        self.mulligan_counts = {}
        self.mulligan_sequence = {}
        self.priority_sequence = None
        self.consecutive_passes = 0
        
    def reset_state(self):
        self.state = {}
        self.player_ids = []
        self.mulligan_choices = {}
        self.mulligan_counts = {}
        self.mulligan_sequence = {}
        self.priority_sequence = None
        self.consecutive_passes = 0

    def start_game_setup(self):

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
            "turn": 0,
            "phase": "MULLIGAN",
            "active_player": first_player,
            "priority_holder": None,
            "life_totals": {p1: 20, p2: 20},
            "hand": {p1: hand_p1, p2: hand_p2},
            "libraries": {p1: deck_p1, p2: deck_p2},
            "battlefield": {p1: [], p2: []},
            "graveyard": {p1: [], p2: []},
            "hand_counts": {p1: 7, p2: 7},
            "stack": [],
            "land_played_this_turn": False
        }
        
        self.mulligan_choices = {p1: False, p2: False}
        self.mulligan_counts = {p1: 0, p2: 0}
        self.mulligan_sequence = {}
        
        self.send_personalized_state_update()
        self.server.phase = "MULLIGAN"
        
        
    def send_personalized_state_update(self, target_player=None):
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
                "library_counts": {p1: len(self.state["libraries"][p1]), 
                              p2: len(self.state["libraries"][p2])},
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
            
            if self.state.get("phase") == "MULLIGAN":
                self.mulligan_sequence[p] = seq_num
                
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
                    self.handle_priority_pass(player_id, pdu)
                case "CAST_SPELL":
                    self.handle_cast_spell(player_id, pdu)
                case "PLAY_LAND":
                    self.handle_play_land(player_id, pdu)
                case "DISCARD":
                    self.handle_discard(player_id, pdu)
                case "CONCEDE":
                    self.game_over(loser_id=player_id, reason="CONCEDE")
                
                    
    def handle_mulligan(self, player_id, pdu):
        seq = pdu.get("seq_num")
        expected_seq = self.mulligan_sequence.get(player_id)
        if expected_seq is not None and seq != expected_seq:
            self.send_error(player_id, "STALE_ACTION", f"Expected sequence number {expected_seq}, but got {seq}.", pdu)
            return
        
        keep = pdu.get("keep", True)
        
        if keep:
            cards_to_bottom = pdu.get("cards_to_bottom", [])
            expected_bottom = self.mulligan_counts[player_id]
            
            if len(cards_to_bottom) != expected_bottom:
                self.send_error(player_id, "ILLEGAL_ACTION", f"Expected to bottom {expected_bottom} cards, but got {len(cards_to_bottom)}.", pdu)
                return
            
            hand = self.state["hand"][player_id]
            # Verify that the cards to bottom are actually in the player's hand
            temp_hand = list(hand)
        
            try:
                for card_id in cards_to_bottom:
                    temp_hand.remove(card_id)
            except ValueError:
                self.send_error(player_id, "ILLEGAL_ACTION", "One or more cards to bottom are not in the player's hand.", pdu)
                return
        
            self.state["hand"][player_id] = temp_hand
            self.state["libraries"][player_id].extend(cards_to_bottom)
            
            self.mulligan_choices[player_id] = True
            
            if len(self.mulligan_choices) == 2 and all(self.mulligan_choices.values()):
                self.transition_to_game()
        else:
            self.mulligan_counts[player_id] += 1
            
            self.mulligan_choices[player_id] = False
            
            hand = self.state["hand"][player_id]
            library = self.state["libraries"][player_id]
            library.extend(hand)
            random.shuffle(library)
            
            self.state["hand"][player_id] = library[:7]
            self.state["libraries"][player_id] = library[7:]
            
            self.send_personalized_state_update(target_player=player_id)
            
    def transition_to_game(self):
        if not all(self.mulligan_choices.values()):
            return
        
        self.state["phase"] = "IN_GAME"
        self.state["turn"] = 1
        
        self.broadcast_phase_transition("MULLIGAN", "UNTAP")
        
        self.state["phase"] = "UNTAP"
        self.state["land_played_this_turn"] = False
        
        self.send_personalized_state_update()
        
        self.broadcast_phase_transition("UNTAP", "UPKEEP")
        self.state["phase"] = "UPKEEP"
        
        self.grant_priority(self.state["active_player"])
        
    def broadcast_phase_transition(self, from_phase, to_phase):
        self.server.broadcast({
            "type": "PHASE_TRANSITION",
            "seq_num": self.server.get_next_sequence_number(),
            "from_phase": from_phase,
            "to_phase": to_phase,
            "active_player": self.state["active_player"],
            "turn": self.state["turn"]
        })
        
            
    def handle_priority_pass(self, player_id, pdu):
        seq = pdu.get("seq_num")
        
        if self.state.get("priority_holder") != player_id:
            self.send_error(player_id, "NOT_YOUR_PRIORITY", "You do not currently hold priority.", pdu, seq)
            return
        
        if seq != self.priority_sequence:
            self.send_error(player_id, "STALE_ACTION", f"Expected sequence number {self.priority_sequence}, but got {seq}.", pdu)
            self.regrant_priority(player_id)
            return
        
        self.consecutive_passes += 1
        
        if self.consecutive_passes >= 2:
            self.consecutive_passes = 0
            if self.state["stack"]:
                self.resolve_top_stack()
                
    def resolve_top_stack(self):
        item = self.state["stack"].pop(-1)
        
        self.server.broadcast({
            "type": "STACK_RESOLVE",
            "seq_num": self.server.get_next_sequence_number(),
            "stack_item_id": item["stack_item_id"],
            "result": "RESOLVED",
            "state_changes": []
        })
        # TODO: Implement the actual resolution logic for the stack item here
        
            
    def handle_cast_spell(self, player_id, pdu):
        # TODO: Implement spell casting logic here
        self.send_personalized_state_update()
    
    def handle_play_land(self, player_id, pdu):
        # TODO: Implement land playing logic here
        self.send_personalized_state_update()
    
    def handle_discard(self, player_id, pdu):
        # TODO: Implement discard logic here
        self.send_personalized_state_update()
        
    def grant_priority(self, player_id):
        if self.check_state_based_actions():
            return
        
        self.state["priority_holder"] = player_id
        seq_num = self.server.get_next_sequence_number()
        self.priority_sequence = seq_num
        self.server.send_to_player(player_id, {
            "type": "PRIORITY_GRANT",
            "player_id": player_id,
            "seq_num": seq_num,
            "time_limit_ms": 60000
        })
        
    def send_error(self, player_id, code, message, pdu, seq=None):
        self.server.send_to_player(player_id, {
            "type": "ERROR",
            "seq_num": seq if seq is not None else self.server.get_next_sequence_number(),
            "code": code,
            "message": message,
            "rejected_action": pdu
        })
    
    def regrant_priority(self, player_id):
        if self.state.get["priority_holder"] == player_id and self.priority_sequence is not None:
            self.server.send_to_player(player_id, {
                "type": "PRIORITY_GRANT",
                "player_id": player_id,
                "seq_num": self.priority_sequence,
                "time_limit_ms": 60000
            })
                
    def check_state_based_actions(self):
        if self.server.phase != "IN_GAME":
            return False
        p1, p2 = self.player_ids[0], self.player_ids[1]
        life_p1 = self.state["life_totals"][p1]
        life_p2 = self.state["life_totals"][p2]
        
        if life_p1 <= 0 and life_p2 <= 0:
            ap = self.state["active_player"]
            self.game_over(loser_id=ap, reason="LIFE_ZERO")
            return True
        elif life_p1 <= 0:
            self.game_over(loser_id=p1, reason="LIFE_ZERO")
            return True
        elif life_p2 <= 0:
            self.game_over(loser_id=p2, reason="LIFE_ZERO")
            return True

        return False
    
    def handle_discard(self, player_id, pdu):
        seq = pdu.get("seq_num")
        ap = self.state["active_player"]
        
        if self.state["phase"] != "CLEANUP" or player_id != ap:
            self.send_error(player_id, "ILLEGAL_ACTION", "Can only discard during your cleanup step.", pdu, seq)
            return
        
        card_ids = pdu.get("card_ids", [])
        hand = self.state["hand"][player_id]
        
        temp_hand = list(hand)
        try:
            for card in card_ids:
                temp_hand.remove(card)
        except ValueError:
            self.send_error(player_id, "ILLEGAL_ACTION", "Discarded cards not in hand.", pdu, seq)
            return
        
        self.state["hand"][player_id] = temp_hand
        self.state["graveyard"][player_id].extend(card_ids)
        
        if len(self.state["hand"][player_id]) > 7:
            self.send_personalized_state_update()
        else:
            self.send_personalized_state_update()
            self.end_turn()
            
    def end_turn(self):
        self.state["turn"] += 1
        
        ap = self.state["active_player"]
        nap = self.player_ids[1] if ap == self.player_ids[0] else self.player_ids[0]
        
        self.state["active_player"] = nap
        
        self.broadcast_phase_transition("CLEANUP", "UNTAP")
        self.state["phase"] = "UNTAP"
        
        self.state["land_played_this_turn"] = False
        self.send_personalized_state_update()
        
        self.broadcast_phase_transition("UNTAP", "UPKEEP")
        self.state["phase"] = "UPKEEP"
        self.grant_priority(nap)
        
        
    
    def game_over(self, loser_id, reason):
        if not self.player_ids:
            return
        
        if reason == "LIFE_ZERO":
            if self.state.get("life_totals", {}).get(self.state.get("active_player")) is not None and self.state["life_totals"][self.state["active_player"]] <= 0:
                winner_id = self.player_ids[1] if self.state["active_player"] == self.player_ids[0] else self.player_ids[0]
            else:
                winner_id = self.player_ids[1] if loser_id == self.player_ids[0] else self.player_ids[0]
        elif reason == "CONCEDE":
            winner_id = self.player_ids[1] if loser_id == self.player_ids[0] else self.player_ids[0]
        elif reason == "DISCONNECT":
            winner_id = self.player_ids[1] if loser_id == self.player_ids[0] else self.player_ids[0]
        else:
            winner_id = self.player_ids[1] if loser_id == self.player_ids[0] else self.player_ids[0]
            
        self.server.broadcast({
            "type": "GAME_OVER",
            "seq_num": self.server.get_next_sequence_number(),
            "winner_id": winner_id,
            "loser_id": loser_id,
            "reason": reason
        })
        self.server.phase = "LOBBY"
        self.server.reset_lobby_state()

    def stop(self):
        self.state = "stopped"
        print("Game stopped.")

    def update(self):
        if self.state == "running":
            print("Game is updating...")
        else:
            print("Game is not running.")