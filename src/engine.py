import copy
import random
from turn_manager import GameRuleError, PRIORITY_STEPS, TurnManager


# Minimal fixed-catalog effects owned jointly by Dev 3/4. Unknown cards are
# still represented on the stack but resolve without a special effect.
CARD_EFFECTS = {
    "lightning_bolt": {"kind": "DAMAGE", "amount": 3},
    "shock": {"kind": "DAMAGE", "amount": 2},
    "counterspell": {"kind": "COUNTER"},
    "goblin_guide": {"kind": "CREATURE", "power": 2, "toughness": 2, "haste": True},
}

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
        self.turn_manager = None
        
    def reset_state(self):
        self.state = {}
        self.player_ids = []
        self.mulligan_choices = {}
        self.mulligan_counts = {}
        self.mulligan_sequence = {}
        self.priority_sequence = None
        self.consecutive_passes = 0
        self.turn_manager = None

    def start_game_setup(self):

        self.player_ids = list(self.server.players.keys())
        
        p1, p2 = self.player_ids[0], self.player_ids[1]
        
    
        deck_p1 = copy.deepcopy(self.server.players[p1]['deck'])
        deck_p2 = copy.deepcopy(self.server.players[p2]['deck'])
        
        random.shuffle(deck_p1)
        random.shuffle(deck_p2)
        
        hand_p1 = [deck_p1.pop() for _ in range(min(len(deck_p1), 7))]
        hand_p2 = [deck_p2.pop() for _ in range(min(len(deck_p2), 7))]
        
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
            "hand_counts": {p1: len(hand_p1), p2: len(hand_p2)},
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

            self.server.send_to_player(p, pdu)
            
        
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
                case "ACTIVATE_ABILITY":
                    self.handle_activate_ability(player_id, pdu)
                case "DISCARD":
                    self.handle_discard(player_id, pdu)
                case "CONCEDE":
                    # self.game_over(loser_id=player_id, reason="CONCEDE")
                    self.handle_concede(player_id, pdu)
                    
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
        
        self.server.phase = "IN_GAME"
        self.turn_manager = TurnManager(self.state, self.player_ids)
        for from_phase, to_phase in self.turn_manager.begin_game():
            self.state["phase"] = to_phase
            self.broadcast_phase_transition(from_phase, to_phase)
            if to_phase == "UNTAP":
                self.send_personalized_state_update()
        self.grant_priority(self.state["active_player"])
        
    def broadcast_phase_transition(self, from_phase, to_phase):
        pdu = {
            "type": "PHASE_TRANSITION",
            "seq_num": self.server.get_next_sequence_number(),
            "from_phase": from_phase,
            "to_phase": to_phase,
            "active_player": self.state["active_player"],
            "turn": self.state["turn"]
        }

        print(f"[engine] Broadcasting PHASE_TRANSITION: {pdu}")
        self.server.broadcast(pdu)

    def _validate_priority_action(self, player_id, pdu):
        seq = pdu.get("seq_num")

        if self.state.get("priority_holder") != player_id:
            self.send_error(player_id, "NOT_YOUR_PRIORITY", "You do not currently hold priority.", pdu, seq)
            return False

        if seq != self.priority_sequence:
            self.send_error(player_id, "STALE_ACTION",
                            f"Expected sequence number {self.priority_sequence}, but got {seq}.", pdu)
            self.regrant_priority(player_id)
            return False

        return True

    def handle_priority_pass(self, player_id, pdu):
        if not self._validate_priority_action(player_id, pdu):
            return
        
        try:
            outcome = self.turn_manager.pass_priority(player_id)
        except GameRuleError as error:
            self.send_error(player_id, error.code, error.message, pdu)
            return

        if outcome == "TRANSFER":
            self.grant_priority(self.state["priority_holder"])
        elif outcome == "RESOLVE":
            self.resolve_top_stack()
        else:
            self.advance_phase()

    def handle_concede(self, player_id, pdu):
        seq = pdu.get("seq_num")
        expected_seq = self.server.players.get(player_id, {}).get("last_seq_sent")

        if expected_seq is not None and seq != expected_seq:
            self.send_error(player_id, "STALE_ACTION", f"Expected sequence number {expected_seq}, but got {seq}.", pdu)
            return

        self.game_over(loser_id=player_id, reason="CONCEDE")
                
    def resolve_top_stack(self):
        item = self.turn_manager.pop()
        legal_targets = [target for target in item.targets if self.turn_manager.target_is_legal(target)]
        if item.targets and not legal_targets:
            result, state_changes = "FIZZLE", []
        else:
            result = "RESOLVED"
            state_changes = self._apply_stack_effect(item, legal_targets)
        if item.item_type == "SPELL" and item.effect.get("kind") != "CREATURE":
            self.state["graveyard"][item.controller].append(item.source)

        stack_resolve_pdu = {
            "type": "STACK_RESOLVE",
            "seq_num": self.server.get_next_sequence_number(),
            "stack_item_id": item.stack_item_id,
            "result": result,
            "state_changes": state_changes
        }

        print(f"[engine] Received {stack_resolve_pdu}")
        self.server.broadcast(stack_resolve_pdu)

        if self.check_state_based_actions():
            return
        self.send_personalized_state_update()
        self.grant_priority(self.state["active_player"])
            
    def handle_cast_spell(self, player_id, pdu):
        if not self._validate_priority_action(player_id, pdu):
            return
        card_id = pdu.get("card_id")
        if card_id not in self.state["hand"][player_id]:
            self.send_error(player_id, "ILLEGAL_ACTION", "The selected card is not in your hand.", pdu)
            return
        effect = self._effect_for(card_id)
        if effect.get("sorcery", effect.get("kind") == "CREATURE") and not self.turn_manager.is_sorcery_speed(player_id):
            self.send_error(player_id, "WRONG_PHASE", "This spell may only be cast at sorcery speed.", pdu)
            return
        targets = pdu.get("targets", [])
        if effect.get("kind") in {"DAMAGE", "COUNTER"} and not targets:
            self.send_error(player_id, "ILLEGAL_TARGET", "This spell requires a target.", pdu)
            return
        try:
            self.turn_manager.pay_mana(player_id, pdu.get("mana_payment", {}))
        except GameRuleError as error:
            self.send_error(player_id, error.code, error.message, pdu)
            return
        self.state["hand"][player_id].remove(card_id)
        self.state["hand_counts"][player_id] = len(self.state["hand"][player_id])
        item = self.turn_manager.push("SPELL", card_id, player_id, targets, effect)
        self.server.broadcast({"type": "STACK_PUSH", "seq_num": self.server.get_next_sequence_number(), **item.public()})
        self.send_personalized_state_update()
        self.grant_priority(player_id)
    
    def handle_play_land(self, player_id, pdu):
        if not self._validate_priority_action(player_id, pdu):
            return
        try:
            self.turn_manager.play_land(player_id, pdu.get("card_id"))
        except GameRuleError as error:
            self.send_error(player_id, error.code, error.message, pdu)
            return
        self.send_personalized_state_update()
        self.grant_priority(player_id)

    def handle_activate_ability(self, player_id, pdu):
        if not self._validate_priority_action(player_id, pdu):
            return
        source_id = pdu.get("source_id")
        permanent = next((card for card in self.state["battlefield"][player_id]
                          if isinstance(card, dict) and card.get("id") == source_id), None)
        if permanent is None:
            self.send_error(player_id, "ILLEGAL_ACTION", "Ability source is not under your control.", pdu)
            return
        payment = pdu.get("cost_payment", {})
        if payment.get("tap") and permanent.get("tapped"):
            self.send_error(player_id, "ILLEGAL_ACTION", "The ability source is already tapped.", pdu)
            return
        if payment.get("tap"):
            permanent["tapped"] = True
        abilities = permanent.get("abilities", [])
        ability_index = pdu.get("ability_index")
        if not isinstance(ability_index, int) or ability_index < 0 or ability_index >= len(abilities):
            if payment.get("tap"):
                permanent["tapped"] = False
            self.send_error(player_id, "ILLEGAL_ACTION", "ability_index does not identify an ability.", pdu)
            return
        item = self.turn_manager.push("ABILITY", source_id, player_id, pdu.get("targets", []),
                                      abilities[ability_index])
        self.server.broadcast({"type": "STACK_PUSH", "seq_num": self.server.get_next_sequence_number(), **item.public()})
        self.send_personalized_state_update()
        self.grant_priority(player_id)
    
    # def handle_discard(self, player_id, pdu):
    #     # TODO: Implement discard logic here
    #     self.send_personalized_state_update()

    def advance_phase(self):
        try:
            from_phase, to_phase = self.turn_manager.advance_priority_step()
        except GameRuleError:
            # BEGIN_COMBAT is the explicit hand-off to Dev 4's combat machine.
            return
        self.broadcast_phase_transition(from_phase, to_phase)
        if to_phase == "CLEANUP":
            self.send_personalized_state_update()
            if len(self.state["hand"][self.state["active_player"]]) <= 7:
                self.end_turn()
            return
        self.send_personalized_state_update()
        if to_phase in PRIORITY_STEPS:
            self.grant_priority(self.state["active_player"])

    @staticmethod
    def _effect_for(card_id):
        name = str(card_id).lower()
        for prefix, effect in CARD_EFFECTS.items():
            if name.startswith(prefix):
                return dict(effect)
        return {}

    def _apply_stack_effect(self, item, legal_targets):
        effect = item.effect
        changes = []
        if effect.get("kind") == "DAMAGE" and legal_targets:
            target, amount = legal_targets[0], effect["amount"]
            if target in self.player_ids:
                self.state["life_totals"][target] -= amount
            else:
                for zone in self.state["battlefield"].values():
                    for permanent in zone:
                        if isinstance(permanent, dict) and permanent.get("id") == target:
                            permanent["damage"] = permanent.get("damage", 0) + amount
            changes.append({"change_type": "DAMAGE", "target": target, "amount": amount})
        elif effect.get("kind") == "COUNTER" and legal_targets:
            target = legal_targets[0]
            for index, public in enumerate(self.state["stack"]):
                if public["stack_item_id"] == target:
                    self.state["stack"].pop(index)
                    countered = self.turn_manager.stack_items.pop(target)
                    self.state["graveyard"][countered.controller].append(countered.source)
                    changes.append({"change_type": "COUNTER", "target": target})
                    break
        elif effect.get("kind") == "CREATURE":
            self.state["battlefield"][item.controller].append({
                "id": item.source,
                "controller_id": item.controller,
                "tapped": False,
                "damage": 0,
                "power": effect["power"],
                "toughness": effect["toughness"],
                "summoning_sick": not effect.get("haste", False),
            })
            changes.append({"change_type": "ENTER_BATTLEFIELD", "target": item.source})
        return changes

    def grant_priority(self, player_id):
        if self.check_state_based_actions():
            return
        
        self.state["priority_holder"] = player_id
        seq_num = self.server.get_next_sequence_number()
        self.priority_sequence = seq_num

        priority_grant_pdu = {
            "type": "PRIORITY_GRANT",
            "player_id": player_id,
            "seq_num": seq_num,
            "time_limit_ms": 60000
        }

        print(f"[engine] Granting priority to {player_id}: {priority_grant_pdu}")
        self.server.send_to_player(player_id, priority_grant_pdu)
        
    def send_error(self, player_id, code, message, pdu, seq=None):
        error_pdu = {
            "type": "ERROR",
            "seq_num": seq if seq is not None else self.server.get_next_sequence_number(),
            "code": code,
            "message": message,
            "rejected_action": pdu
        }

        print(f"[engine] Sending ERROR to player {player_id}: {error_pdu}")
        self.server.send_to_player(player_id, error_pdu)
    
    def regrant_priority(self, player_id):
        if self.state.get("priority_holder") == player_id and self.priority_sequence is not None:
            regrant_priority_grant_pdu = {
                "type": "PRIORITY_GRANT",
                "player_id": player_id,
                "seq_num": self.priority_sequence,
                "time_limit_ms": 60000
            }

            print(f"[engine] Regranting PRIORITY to player {player_id}: {regrant_priority_grant_pdu}")
            self.server.send_to_player(player_id, regrant_priority_grant_pdu)
                
    def check_state_based_actions(self):
        if self.server.phase != "IN_GAME":
            return False
        if self.turn_manager:
            self.turn_manager.apply_state_based_actions()
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

        if not card_ids:
            self.send_error(player_id, "ILLEGAL_ACTION", "At least one card must be discarded.", pdu, seq)
            return
        
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
        try:
            transitions = self.turn_manager.finish_cleanup()
        except GameRuleError:
            return
        for from_phase, to_phase in transitions:
            self.state["phase"] = to_phase
            self.broadcast_phase_transition(from_phase, to_phase)
            if to_phase == "UNTAP":
                self.send_personalized_state_update()
        self.grant_priority(self.state["active_player"])

        
    
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

        game_over_pdu = {
            "type": "GAME_OVER",
            "seq_num": self.server.get_next_sequence_number(),
            "winner_id": winner_id,
            "loser_id": loser_id,
            "reason": reason
        }

        print(f"[engine] Broadcasting GAME_OVER: {game_over_pdu}")
        self.server.broadcast(game_over_pdu)
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
