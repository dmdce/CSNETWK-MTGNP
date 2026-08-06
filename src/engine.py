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
        """
        name: __init__
        description: Initializes the game engine with a reference to the server and resets game state.
        @param: server (MTGNPServer): The server instance that owns this engine.
        """

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
        """
        name: reset_state
        description: Clears all game state variables to prepare for a new game.
        """

        self.state = {}
        self.player_ids = []
        self.mulligan_choices = {}
        self.mulligan_counts = {}
        self.mulligan_sequence = {}
        self.priority_sequence = None
        self.consecutive_passes = 0
        self.turn_manager = None

    def start_game_setup(self):
        """
        name: start_game_setup
        description: Performs initial deck shuffling, card drawing, and first-player selection,
                     then sends initial state updates.
        """

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
        """
        name: send_personalized_state_update
        description: Sends a GAME_STATE_UPDATE to one or both players, filtering hidden information per player.
        @param: target_player (str or None): If provided, sends only to that player; otherwise sends to both.
        """

        seq_num = self.server.get_next_sequence_number()
        p1, p2 = self.player_ids[0], self.player_ids[1]

        targets = [target_player] if target_player else self.player_ids

        for p in targets:
            opponent = p2 if p == p1 else p1

            visible_state = {
                "turn": self.state["turn"],
                "phase": self.state["phase"],
                "active_player": self.state["active_player"],
                "priority_holder": self.state["priority_holder"],
                "life_totals": copy.deepcopy(self.state["life_totals"]),
                "hand": copy.deepcopy(self.state["hand"][p]),
                "hand_counts": {opponent: self.state["hand_counts"][opponent]},
                "library_counts": {
                    p1: len(self.state["libraries"][p1]),
                    p2: len(self.state["libraries"][p2])
                },
                "battlefield": copy.deepcopy(self.state["battlefield"]),
                "graveyard": copy.deepcopy(self.state["graveyard"]),
                "stack": copy.deepcopy(self.state["stack"])
            }

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
        """
        name: handle_pdu
        description: Dispatches incoming player PDUs to the appropriate handler based on the current game phase.
        @param: player_id (str): The ID of the player who sent the PDU.
        @param: pdu (dict): The received PDU.
        """

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
        """
        name: handle_mulligan
        description: Processes a MULLIGAN_CHOICE PDU, performing either a keep or a mulligan redraw.
        @param: player_id (str): The player making the choice.
        @param: pdu (dict): The MULLIGAN_CHOICE PDU.
        """

        seq = pdu.get("seq_num")
        expected_seq = self.mulligan_sequence.get(player_id)
        if expected_seq is not None and seq != expected_seq:
            self.server.send_error(player_id, "STALE_ACTION", f"Expected sequence number {expected_seq}, but got {seq}.", pdu)
            return
        
        keep = pdu.get("keep", True)
        
        if keep:
            cards_to_bottom = pdu.get("cards_to_bottom", [])
            expected_bottom = self.mulligan_counts[player_id]
            
            if len(cards_to_bottom) != expected_bottom:
                self.server.send_error(player_id, "ILLEGAL_ACTION", f"Expected to bottom {expected_bottom} cards, but got {len(cards_to_bottom)}.", pdu)
                return
            
            hand = self.state["hand"][player_id]
            # Verify that the cards to bottom are actually in the player's hand
            temp_hand = list(hand)
        
            try:
                for card_id in cards_to_bottom:
                    temp_hand.remove(card_id)
            except ValueError:
                self.server.send_error(player_id, "ILLEGAL_ACTION", "One or more cards to bottom are not in the player's hand.", pdu)
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
        """
        name: transition_to_game
        description: Transitions from MULLIGAN to IN_GAME, initializing the TurnManager and beginning the first turn.
        """

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
        """
        name: broadcast_phase_transition
        description: Sends a PHASE_TRANSITION PDU to all players.
        @param: from_phase (str): The phase being transitioned from.
        @param: to_phase (str): The phase being transitioned to.
        """

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
        """
        name: _validate_priority_action
        description: Checks that the player holds priority and the seq_num matches the current priority token.
        @param: player_id (str): The player attempting the action.
        @param: pdu (dict): The action PDU.
        @return: bool: True if valid, False if an error was sent.
        """

        seq = pdu.get("seq_num")

        if self.state.get("priority_holder") != player_id:
            self.server.send_error(player_id, "NOT_YOUR_PRIORITY", "You do not currently hold priority.", pdu, seq)
            return False

        if seq != self.priority_sequence:
            self.server.send_error(player_id, "STALE_ACTION",
                            f"Expected sequence number {self.priority_sequence}, but got {seq}.", pdu)
            self.regrant_priority(player_id)
            return False

        return True

    def handle_priority_pass(self, player_id, pdu):
        """
        name: handle_priority_pass
        description: Processes a PRIORITY_PASS PDU, transferring priority, resolving stack, or advancing phase.
        @param: player_id (str): The player passing priority.
        @param: pdu (dict): The PRIORITY_PASS PDU.
        """

        if not self._validate_priority_action(player_id, pdu):
            return
        
        try:
            outcome = self.turn_manager.pass_priority(player_id)
        except GameRuleError as error:
            self.server.send_error(player_id, error.code, error.message, pdu)
            return

        if outcome == "TRANSFER":
            self.grant_priority(self.state["priority_holder"])
        elif outcome == "RESOLVE":
            self.resolve_top_stack()
        else:
            self.advance_phase()

    def handle_concede(self, player_id, pdu):
        """
        name: handle_concede
        description: Processes a CONCEDE PDU, ending the game with the conceding player as the loser.
        @param: player_id (str): The player conceding.
        @param: pdu (dict): The CONCEDE PDU.
        """

        seq = pdu.get("seq_num")
        expected_seq = self.server.players.get(player_id, {}).get("last_seq_sent")

        if expected_seq is not None and seq != expected_seq:
            self.server.send_error(player_id, "STALE_ACTION", f"Expected sequence number {expected_seq}, but got {seq}.", pdu)
            return

        self.game_over(loser_id=player_id, reason="CONCEDE")
                
    def resolve_top_stack(self):
        """
        name: resolve_top_stack
        description: Pops the top stack item, applies its effect, broadcasts STACK_RESOLVE, and grants priority.
        """

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
        """
        name: handle_cast_spell
        description: Processes a CAST_SPELL PDU, validates mana and targets, pushes the spell to the stack.
        @param: player_id (str): The player casting the spell.
        @param: pdu (dict): The CAST_SPELL PDU.
        """

        if not self._validate_priority_action(player_id, pdu):
            return
        card_id = pdu.get("card_id")
        if card_id not in self.state["hand"][player_id]:
            self.server.send_error(player_id, "ILLEGAL_ACTION", "The selected card is not in your hand.", pdu)
            return
        effect = self._effect_for(card_id)
        if effect.get("sorcery", effect.get("kind") == "CREATURE") and not self.turn_manager.is_sorcery_speed(player_id):
            self.server.send_error(player_id, "WRONG_PHASE", "This spell may only be cast at sorcery speed.", pdu)
            return
        targets = pdu.get("targets", [])
        if effect.get("kind") in {"DAMAGE", "COUNTER"} and not targets:
            self.server.send_error(player_id, "ILLEGAL_TARGET", "This spell requires a target.", pdu)
            return
        try:
            self.turn_manager.pay_mana(player_id, pdu.get("mana_payment", {}))
        except GameRuleError as error:
            self.server.send_error(player_id, error.code, error.message, pdu)
            return
        self.state["hand"][player_id].remove(card_id)
        self.state["hand_counts"][player_id] = len(self.state["hand"][player_id])
        item = self.turn_manager.push("SPELL", card_id, player_id, targets, effect)
        self.server.broadcast({"type": "STACK_PUSH", "seq_num": self.server.get_next_sequence_number(), **item.public()})
        self.send_personalized_state_update()
        self.grant_priority(player_id)
    
    def handle_play_land(self, player_id, pdu):
        """
        name: handle_play_land
        description: Processes a PLAY_LAND PDU, placing the land on the battlefield if legal.
        @param: player_id (str): The player playing the land.
        @param: pdu (dict): The PLAY_LAND PDU.
        """

        if not self._validate_priority_action(player_id, pdu):
            return
        try:
            self.turn_manager.play_land(player_id, pdu.get("card_id"))
        except GameRuleError as error:
            self.server.send_error(player_id, error.code, error.message, pdu)
            return
        self.send_personalized_state_update()
        self.grant_priority(player_id)

    def handle_activate_ability(self, player_id, pdu):
        """
        name: handle_activate_ability
        description: Processes an ACTIVATE_ABILITY PDU, validates costs, and pushes the ability to the stack.
        @param: player_id (str): The player activating the ability.
        @param: pdu (dict): The ACTIVATE_ABILITY PDU.
        """

        if not self._validate_priority_action(player_id, pdu):
            return
        source_id = pdu.get("source_id")
        permanent = next((card for card in self.state["battlefield"][player_id]
                          if isinstance(card, dict) and card.get("id") == source_id), None)
        if permanent is None:
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Ability source is not under your control.", pdu)
            return
        payment = pdu.get("cost_payment", {})
        if payment.get("tap") and permanent.get("tapped"):
            self.server.send_error(player_id, "ILLEGAL_ACTION", "The ability source is already tapped.", pdu)
            return
        if payment.get("tap"):
            permanent["tapped"] = True
        abilities = permanent.get("abilities", [])
        ability_index = pdu.get("ability_index")
        if not isinstance(ability_index, int) or ability_index < 0 or ability_index >= len(abilities):
            if payment.get("tap"):
                permanent["tapped"] = False
            self.server.send_error(player_id, "ILLEGAL_ACTION", "ability_index does not identify an ability.", pdu)
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
        """
        name: advance_phase
        description: Advances the game phase via the TurnManager, broadcasting PHASE_TRANSITION
                     and granting priority when needed.
        """

        try:
            from_phase, to_phase = self.turn_manager.advance_priority_step()
        except GameRuleError:
            if self.state["phase"] == "BEGIN_COMBAT":
                self.transition_to_declare_attackers()
            return

        if to_phase == "BEGIN_COMBAT":
            self.handle_begin_combat()
            return

        self.broadcast_phase_transition(from_phase, to_phase)

        if to_phase == "CLEANUP":
            self.state["priority_holder"] = None
            self.send_personalized_state_update()
            if len(self.state["hand"][self.state["active_player"]]) <= 7:
                self.end_turn()
            return
        self.send_personalized_state_update()
        if to_phase in PRIORITY_STEPS:
            self.grant_priority(self.state["active_player"])

    def handle_begin_combat(self):
        """Creating Beginning of Combat step setup:

        mutates state, evaluates SBAs, notifies clients, and grants priority.
        """

        from_phase, to_phase = self.turn_manager.begin_combat_step()

        if self.check_state_based_actions():
            return
        self.broadcast_phase_transition(from_phase, to_phase)
        self.send_personalized_state_update()

        self.grant_priority(self.state["active_player"])

    def transition_to_declare_attackers(self):
        """Closes the BEGIN_COMBAT priority window and passes execution

        to the Declare Attackers step (Dev 4 boundary).
        """
        from_phase = self.state["phase"]
        to_phase = "DECLARE_ATTACKERS"

        self.state["phase"] = to_phase
        self.state["priority_holder"] = None

        self.broadcast_phase_transition(from_phase, to_phase)
        self.send_personalized_state_update()

    @staticmethod
    def _effect_for(card_id):
        """
        name: _effect_for
        description: Returns the effect dictionary for a card based on its ID prefix, or an empty dict if unknown.
        @param: card_id (str): The card identifier.
        @return: dict: The effect definition, or an empty dictionary.
        """

        name = str(card_id).lower()
        for prefix, effect in CARD_EFFECTS.items():
            if name.startswith(prefix):
                return dict(effect)
        return {}

    def _apply_stack_effect(self, item, legal_targets):
        """
        name: _apply_stack_effect
        description: Applies the resolved effect of a stack item (damage, counter, creature entry) and returns state changes.
        @param: item (StackItem): The stack item being resolved.
        @param: legal_targets (list): The list of targets that are still legal.
        @return: list: A list of state change dictionaries.
        """

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
        """
        name: grant_priority
        description: Issues a PRIORITY_GRANT PDU to the specified player, updating the priority holder state.
        @param: player_id (str): The player who now holds priority.
        """

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
        
    # def send_error(self, player_id, code, message, pdu, seq=None):
    #     error_pdu = {
    #         "type": "ERROR",
    #         "seq_num": seq if seq is not None else self.server.get_next_sequence_number(),
    #         "code": code,
    #         "message": message,
    #         "rejected_action": pdu
    #     }
    #
    #     print(f"[engine] Sending ERROR to player {player_id}: {error_pdu}")
    #     self.server.send_to_player(player_id, error_pdu)
    
    def regrant_priority(self, player_id):
        """
        name: regrant_priority
        description: Re-sends the current PRIORITY_GRANT PDU with the same sequence number to a player after a stale action.
        @param: player_id (str): The player who should receive the regrant.
        """

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
        """
        name: check_state_based_actions
        description: Checks and applies state-based actions (lethal damage, life zero, etc.)
                     and triggers GAME_OVER if needed.
        @return: bool: True if a GAME_OVER was triggered, False otherwise.
        """

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
        """
        name: handle_discard
        description: Processes a DISCARD PDU during Cleanup, moving cards from hand to graveyard until hand size ≤7.
        @param: player_id (str): The player discarding cards.
        @param: pdu (dict): The DISCARD PDU.
        """

        seq = pdu.get("seq_num")
        ap = self.state["active_player"]
        
        if self.state["phase"] != "CLEANUP" or player_id != ap:
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Can only discard during your cleanup step.", pdu, seq)
            return
        
        card_ids = pdu.get("card_ids", [])
        hand = self.state["hand"][player_id]

        if not card_ids:
            self.server.send_error(player_id, "ILLEGAL_ACTION", "At least one card must be discarded.", pdu, seq)
            return
        
        temp_hand = list(hand)
        try:
            for card in card_ids:
                temp_hand.remove(card)
        except ValueError:
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Discarded cards not in hand.", pdu, seq)
            return
        
        self.state["hand"][player_id] = temp_hand
        self.state["graveyard"][player_id].extend(card_ids)
        
        if len(self.state["hand"][player_id]) > 7:
            self.send_personalized_state_update()
        else:
            self.send_personalized_state_update()
            self.end_turn()
            
    def end_turn(self):
        """
        name: end_turn
        description: Finishes the Cleanup step, clears damage/effects, switches active player, and begins the next turn.
        """

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
        """
        name: game_over
        description: Broadcasts a GAME_OVER PDU, resets the server to LOBBY state, and clears the game engine.
        @param: loser_id (str): The ID of the losing player.
        @param: reason (str): The reason for game over (LIFE_ZERO, CONCEDE, DISCONNECT).
        """

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
        """
        name: stop
        description: (As placeholder) Stops the game engine.
        """

        self.state = "stopped"
        print("Game stopped.")

    def update(self):
        """
        name: update
        description: (As placeholder) Prints current running status.
        """

        if self.state == "running":
            print("Game is updating...")
        else:
            print("Game is not running.")
