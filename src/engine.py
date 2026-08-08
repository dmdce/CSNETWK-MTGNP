import json
import copy
import random
from turn_manager import GameRuleError, PRIORITY_STEPS, TurnManager
from console_logger import get_logger

logger = get_logger(__name__)

# Minimal fixed-catalog effects owned jointly by Dev 3/4. Unknown cards are
# still represented on the stack but resolve without a special effect.
CARD_EFFECTS = {
    "lightning_bolt": {"kind": "DAMAGE", "amount": 3},
    "shock": {"kind": "DAMAGE", "amount": 2},
    "counterspell": {"kind": "COUNTER"},
    "goblin_guide": {"kind": "CREATURE", "power": 2, "toughness": 2, "haste": True},
}

LAND_PREFIXES = ("mountain", "island", "swamp", "forest", "plains")
INSTANT_PREFIXES = (
    "lightning_bolt", "shock", "searing_spear", "skullcrack", "incinerate",
    "counterspell", "cancel", "unsummon", "negate", "mana_leak",
    "giant_growth", "naturalize", "vines_of_vastwood",
    "swords_to_plowshares", "path_to_exile", "healing_salve",
    "dark_ritual", "terror", "doom_blade",
)
SORCERY_PREFIXES = (
    "lava_spike", "flame_slash", "rift_bolt", "ponder", "rampant_growth",
    "raise_dead", "mind_rot",
)

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
        self.last_phase_transition_seq = None
        self.priority_sequence = None
        self.consecutive_passes = 0
        self.turn_manager = None
        self.pending_triggers = []
        self.pending_trigger_choice = None
        self.pending_trigger_order = None
        self.deferred_priority_player = None

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
        self.last_phase_transition_seq = None
        self.priority_sequence = None
        self.consecutive_passes = 0
        self.turn_manager = None
        self.pending_triggers = []
        self.pending_trigger_choice = None
        self.pending_trigger_order = None
        self.deferred_priority_player = None

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

        logger.debug(
            f"Broadcasting state to players:\n%s",
            json.dumps(self.state, indent=2, sort_keys=True))

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
            logger.debug(f"Received IN_GAME action from player {player_id}: {pdu_type}")
            match pdu_type:
                case "PRIORITY_PASS":
                    self.handle_priority_pass(player_id, pdu)
                case "DECLARE_ATTACKERS":
                    self.handle_declare_attackers_pdu(player_id, pdu)
                case "DECLARE_BLOCKERS":
                    self.handle_declare_blockers_pdu(player_id, pdu)
                case "ASSIGN_DAMAGE_ORDER":
                    self.handle_assign_damage_order_pdu(player_id, pdu)
                case "CAST_SPELL":
                    self.handle_cast_spell(player_id, pdu)
                case "PLAY_LAND":
                    self.handle_play_land(player_id, pdu)
                case "ACTIVATE_ABILITY":
                    self.handle_activate_ability(player_id, pdu)
                case "TRIGGER_ORDER_RESPONSE":
                    self.handle_trigger_order_response(player_id, pdu)
                case "TRIGGER_CHOICE_RESPONSE":
                    self.handle_trigger_choice_response(player_id, pdu)
                case "DISCARD":
                    self.handle_discard(player_id, pdu)
                case "CONCEDE":
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
            self.server.send_error(player_id, "STALE_ACTION",
                                   f"Expected sequence number {expected_seq}, but got {seq}.", pdu)
            return

        keep = pdu.get("keep", True)

        if keep:
            cards_to_bottom = pdu.get("cards_to_bottom", [])
            expected_bottom = self.mulligan_counts[player_id]

            if len(cards_to_bottom) != expected_bottom:
                self.server.send_error(player_id, "ILLEGAL_ACTION",
                                       f"Expected to bottom {expected_bottom} cards, but got {len(cards_to_bottom)}.",
                                       pdu)
                return

            hand = self.state["hand"][player_id]
            # Verify that the cards to bottom are actually in the player's hand
            temp_hand = list(hand)

            try:
                for card_id in cards_to_bottom:
                    temp_hand.remove(card_id)
            except ValueError:
                self.server.send_error(player_id, "ILLEGAL_ACTION",
                                       "One or more cards to bottom are not in the player's hand.", pdu)
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
            self.queue_trigger_event("STEP_PHASE_BEGIN", {"phase": to_phase})
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

        seq_num = self.server.get_next_sequence_number()
        self.last_phase_transition_seq = seq_num

        pdu = {
            "type": "PHASE_TRANSITION",
            "seq_num": seq_num,
            "from_phase": from_phase,
            "to_phase": to_phase,
            "active_player": self.state["active_player"],
            "turn": self.state["turn"]
        }

        logger.debug(f"Broadcasting PHASE_TRANSITION: {pdu}")
        self.server.broadcast(pdu)

    def transition_to_declare_attackers(self):
        """
        name: transition_to_declare_attackers
        description: Transitions state from BEGIN_COMBAT to DECLARE_ATTACKERS and syncs clients.
        """
        from_phase = self.state["phase"]
        to_phase = "DECLARE_ATTACKERS"

        self.state["phase"] = to_phase
        self.state["priority_holder"] = None

        self.broadcast_phase_transition(from_phase, to_phase)
        self.send_personalized_state_update()

    def handle_declare_attackers_pdu(self, player_id, pdu):
        """
        name: handle_declare_attackers_pdu
        description: Normalizes attacker PDU payloads, validates against turn_manager rules,
                     and updates engine battlefield state.
        @param: player_id (str): The player declaring attackers.
        @param: pdu (dict): The DECLARE_ATTACKERS PDU.
        """
        if self.state["phase"] != "DECLARE_ATTACKERS":
            self.server.send_error(player_id, "ILLEGAL_ACTION",
                                   "Cannot declare attackers outside DECLARE_ATTACKERS step.", pdu)
            return

        if player_id != self.state["active_player"]:
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Only the active player can declare attackers.", pdu)
            return

        seq = pdu.get("seq_num")
        if self.last_phase_transition_seq is not None and seq != self.last_phase_transition_seq:
            self.server.send_error(
                player_id,
                "STALE_ACTION",
                f"Expected sequence number {self.last_phase_transition_seq}, but got {seq}.",
                pdu
            )
            return

        raw_attackers = pdu.get("attackers", [])
        if not isinstance(raw_attackers, list):
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Attackers field must be a list.", pdu)
            return

        # Normalize incoming payload format: convert string IDs into dicts with default target
        opponent_id = self.turn_manager.opponent(player_id)
        normalized_attackers = []

        for item in raw_attackers:
            if isinstance(item, str):
                normalized_attackers.append({"creature_id": item, "target": opponent_id})
            elif isinstance(item, dict):
                entry = dict(item)
                entry.setdefault("target", opponent_id)
                normalized_attackers.append(entry)
            else:
                self.server.send_error(player_id, "ILLEGAL_ACTION", "Invalid attacker element format.", pdu)
                return

        # Let TurnManager perform core validation (tapped, summoning_sick, wrong_phase)
        try:
            self.turn_manager.declare_attackers(player_id, normalized_attackers)
        except GameRuleError as e:
            self.server.send_error(player_id, e.code, e.message, pdu)
            return

        self.send_personalized_state_update()

        # Priority window opens after declaring attackers if combat moves forward
        if self.state["phase"] == "DECLARE_BLOCKERS":
            self.grant_priority(self.state["active_player"])

    def handle_declare_blockers_pdu(self, player_id, pdu):
        """
        name: handle_declare_blockers_pdu
        description: Processes DECLARE_BLOCKERS PDU sent by non-active player.
        @param: player_id (str): The player declaring attackers.
        @param: pdu (dict): The DECLARE_ATTACKERS PDU.
        """
        if self.state["phase"] != "DECLARE_BLOCKERS":
            self.server.send_error(player_id, "ILLEGAL_ACTION",
                                   "Cannot declare blockers outside DECLARE_BLOCKERS step.", pdu)
            return

        if self.state["phase"] in ("FIRST_STRIKE_DAMAGE", "COMBAT_DAMAGE"):
            self.handle_combat_damage_phase()

        if player_id == self.state["active_player"]:
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Non-active player must declare blockers.", pdu)
            return

        seq = pdu.get("seq_num")
        if self.last_phase_transition_seq is not None and seq != self.last_phase_transition_seq:
            self.server.send_error(player_id, "STALE_ACTION",
                                   f"Expected sequence number {self.last_phase_transition_seq}, but got {seq}.", pdu)
            return

        blockers = pdu.get("blockers", [])

        try:
            self.turn_manager.declare_blockers(player_id, blockers)
        except GameRuleError as e:
            self.server.send_error(player_id, e.code, e.message, pdu)
            return

        # Broadcast updated state showing "blocking" relations while "tapped" remains False
        self.send_personalized_state_update()

        # Check if phase advanced directly into combat damage
        if self.state["phase"] in ("FIRST_STRIKE_DAMAGE", "COMBAT_DAMAGE"):
            self.handle_combat_damage_phase()
        else:
            self.grant_priority(self.state["active_player"])

    def handle_assign_damage_order_pdu(self, player_id, pdu):
        """
        Processes ASSIGN_DAMAGE_ORDER PDU sent by the active player for a multiply-blocked attacker.
        """
        if self.state["phase"] != "ASSIGN_DAMAGE_ORDER":
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Cannot assign damage order outside ASSIGN_DAMAGE_ORDER phase.", pdu)
            return

        if player_id != self.state["active_player"]:
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Only active player can assign damage order.", pdu)
            return

        attacker_id = pdu.get("attacker_id")
        ordered_blocker_ids = pdu.get("ordered_blocker_ids", [])

        if not attacker_id or not isinstance(ordered_blocker_ids, list):
            self.server.send_error(player_id, "ILLEGAL_ACTION", "PDU must specify attacker_id and ordered_blocker_ids list.", pdu)
            return

        try:
            self.turn_manager.assign_damage_order(player_id, attacker_id, ordered_blocker_ids)
        except GameRuleError as e:
            self.server.send_error(player_id, e.code, e.message, pdu)
            return

        self.send_personalized_state_update()

        # Grant priority once all damage orders have been resolved and phase moves to COMBAT_DAMAGE
        if self.state["phase"] in ("FIRST_STRIKE_DAMAGE", "COMBAT_DAMAGE"):
            self.handle_combat_damage_phase()
        else:
            self.grant_priority(self.state["active_player"])

    def handle_combat_damage_phase(self):
        """
        Processes combat damage resolution and priority transitions.
        Called after declare_blockers, assign_damage_order, or phase advancement.
        """
        current_phase = self.state.get("phase")

        if current_phase in ("FIRST_STRIKE_DAMAGE", "COMBAT_DAMAGE"):
            is_first_strike = (current_phase == "FIRST_STRIKE_DAMAGE")

            # Resolve combat damage via TurnManager
            result = self.turn_manager.resolve_combat_damage_step(is_first_strike=is_first_strike)

            # 1. Broadcast COMBAT_DAMAGE_RESULT per RFC spec
            damage_result_pdu = {
                "type": "COMBAT_DAMAGE_RESULT",
                "seq_num": self.server.get_next_sequence_number(),
                "damage_events": result.get("damage_events", []),
                "life_totals": copy.deepcopy(self.state.get("life_totals", {})),
                "creatures_died": result.get("creatures_died", [])
            }
            self.server.broadcast(damage_result_pdu)

            # 2. Broadcast updated game states to each client
            self.send_personalized_state_update()

            # 3. Transition to END_OF_COMBAT phase
            trans_seq = self.server.get_next_sequence_number()
            transition_pdu = {
                "type": "PHASE_TRANSITION",
                "seq_num": trans_seq,
                "from_phase": current_phase,
                "to_phase": "END_OF_COMBAT",
                "active_player": self.state["active_player"],
                "turn": self.state.get("turn", 1)
            }
            self.state["phase"] = "END_OF_COMBAT"
            self.server.broadcast(transition_pdu)

            # 4. Open Priority Window at End of Combat
            self.grant_priority(self.state["active_player"])

    def handle_end_of_combat_phase(self):
        """
        Clears combat-related state and advances the turn to POSTCOMBAT_MAIN.
        Executed after both players pass priority consecutively in END_OF_COMBAT.
        """
        # 1. Clear all combat-related state
        self.turn_manager.clear_combat_state()

        # 2. Advance phase to POSTCOMBAT_MAIN
        trans_seq = self.server.get_next_sequence_number()
        transition_pdu = {
            "type": "PHASE_TRANSITION",
            "seq_num": trans_seq,
            "from_phase": "END_OF_COMBAT",
            "to_phase": "POSTCOMBAT_MAIN",
            "active_player": self.state["active_player"],
            "turn": self.state.get("turn", 1)
        }
        self.state["phase"] = "POSTCOMBAT_MAIN"
        self.server.broadcast(transition_pdu)

        # 3. Send state updates and grant priority to Active Player for Postcombat Main
        self.send_personalized_state_update()
        self.grant_priority(self.state["active_player"])

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
            self.server.send_error(player_id, "STALE_ACTION", f"Expected sequence number {self.priority_sequence}, but got {seq}.", pdu)
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
            # Handle combat hand-off exception if pass_priority raises error at phase boundary
            if self.state.get("phase") == "BEGIN_COMBAT":
                self.transition_to_declare_attackers()
                return
            self.server.send_error(player_id, error.code, error.message, pdu)
            return

        if outcome == "TRANSFER":
            self.grant_priority(self.state["priority_holder"])
        elif outcome == "RESOLVE":
            self.resolve_top_stack()
        elif outcome == "DECLARE_ATTACKERS":
            self.transition_to_declare_attackers()
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
            if any(change.get("change_type") == "ENTER_BATTLEFIELD" for change in state_changes):
                self.queue_trigger_event("PERMANENT_ETB", {
                    "source_id": item.source_id,
                    "controller_id": item.controller_id,
                })
        if item.item_type == "SPELL" and item.effect.get("kind") not in {"CREATURE", "PERMANENT"}:
            self.state["graveyard"][item.controller].append(item.source)

        stack_resolve_pdu = {
            "type": "STACK_RESOLVE",
            "seq_num": self.server.get_next_sequence_number(),
            "stack_item_id": item.stack_item_id,
            "result": result,
            "state_changes": state_changes
        }

        logger.debug(f"Received {stack_resolve_pdu}")
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
        if effect.get("sorcery", effect.get("kind") in {"CREATURE", "PERMANENT"}) and not self.turn_manager.is_sorcery_speed(player_id):
            self.server.send_error(player_id, "WRONG_PHASE", "This spell may only be cast at sorcery speed.", pdu)
            return
        if effect.get("kind") == "LAND":
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Lands must be played with PLAY_LAND.", pdu)
            return
        targets = pdu.get("targets", [])
        if effect.get("kind") in {"DAMAGE", "COUNTER"} and not targets:
            self.server.send_error(player_id, "ILLEGAL_TARGET", "This spell requires a target.", pdu)
            return
        if any(not self.turn_manager.target_is_legal(target) for target in targets):
            self.server.send_error(player_id, "ILLEGAL_TARGET", "One or more selected targets are illegal.", pdu)
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
        self.queue_trigger_event("SPELL_CAST", {"source_id": card_id, "controller_id": player_id})
        self.send_personalized_state_update()
        self.grant_priority(player_id)

    def handle_play_land(self, player_id, pdu):
        """
        name: handle_play_land
        description: Processes a PLAY_LAND PDU, placing the land on the battlefield if legal.
        @param: player_id (str): The player playing the land.
        @param: pdu (dict): The PLAY_LAND PDU.
        """

        if player_id != self.state.get("active_player"):
            self.server.send_error(player_id, "ILLEGAL_ACTION", "Only the active player may play a land.", pdu)
            return
        expected_seq = self.server.players.get(player_id, {}).get("last_seq_sent") or self.priority_sequence
        if pdu.get("seq_num") != expected_seq:
            self.server.send_error(player_id, "STALE_ACTION",
                                   f"Expected sequence number {expected_seq}, but got {pdu.get('seq_num')}.", pdu)
            return
        try:
            self.turn_manager.play_land(player_id, pdu.get("card_id"))
        except GameRuleError as error:
            self.server.send_error(player_id, error.code, error.message, pdu)
            return
        self.queue_trigger_event("PERMANENT_ETB", {"source_id": pdu.get("card_id"), "controller_id": player_id})
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
        abilities = permanent.get("abilities", [])
        ability_index = pdu.get("ability_index")
        if not isinstance(ability_index, int) or ability_index < 0 or ability_index >= len(abilities):
            self.server.send_error(player_id, "ILLEGAL_ACTION", "ability_index does not identify an ability.", pdu)
            return
        if payment.get("tap") and permanent.get("tapped"):
            self.server.send_error(player_id, "ILLEGAL_ACTION", "The ability source is already tapped.", pdu)
            return
        targets = pdu.get("targets", [])
        if any(not self.turn_manager.target_is_legal(target) for target in targets):
            self.server.send_error(player_id, "ILLEGAL_TARGET", "One or more selected targets are illegal.", pdu)
            return
        try:
            self.turn_manager.pay_mana(player_id, pdu.get("mana_payment", payment.get("mana", {})))
        except GameRuleError as error:
            self.server.send_error(player_id, error.code, error.message, pdu)
            return
        if payment.get("tap"):
            permanent["tapped"] = True
        # abilities = permanent.get("abilities", [])
        # ability_index = pdu.get("ability_index")
        # if not isinstance(ability_index, int) or ability_index < 0 or ability_index >= len(abilities):
        #     if payment.get("tap"):
        #         permanent["tapped"] = False
        #     self.server.send_error(player_id, "ILLEGAL_ACTION", "ability_index does not identify an ability.", pdu)
        #     return
        item = self.turn_manager.push("ABILITY", source_id, player_id, pdu.get("targets", []),
                                      abilities[ability_index])
        self.server.broadcast({"type": "STACK_PUSH", "seq_num": self.server.get_next_sequence_number(), **item.public()})
        self.queue_trigger_event("ABILITY_CAST", {"source_id": source_id, "controller_id": player_id})
        self.send_personalized_state_update()
        self.grant_priority(player_id)

    def advance_phase(self):
        """
        name: advance_phase
        description: Advances the game phase via the TurnManager, broadcasting PHASE_TRANSITION
                     and granting priority when needed.
        """
        current_phase = self.state.get("phase")

        # 1. Direct handling for steps with custom end-of-step handlers
        if current_phase == "END_OF_COMBAT":
            self.handle_end_of_combat_phase()
            return

        try:
            from_phase, to_phase = self.turn_manager.advance_priority_step()
        except GameRuleError as error:
            if error.code == "DECK_EMPTY":
                self.game_over(loser_id=self.state["active_player"], reason="DECK_EMPTY")
            return

        # handle BEGIN_COMBAT & other phase transition
        if to_phase == "BEGIN_COMBAT":
            from_phase, to_phase = self.turn_manager.begin_combat()

        self.state["phase"] = to_phase
        self.broadcast_phase_transition(from_phase, to_phase)

        if to_phase in ("FIRST_STRIKE_DAMAGE", "COMBAT_DAMAGE"):
            self.handle_combat_damage_phase()
            return

        self.broadcast_phase_transition(from_phase, to_phase)
        self.queue_trigger_event("STEP_PHASE_BEGIN", {"phase": to_phase})
        if to_phase == "DRAW" and self.state["turn"] != 1:
            if self.turn_manager.last_draw_failed:
                self.game_over(self.state["active_player"], "DECK_EMPTY")
                return
            self.queue_trigger_event("CARD_DRAWN", {"player_id": self.state["active_player"]})
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
        if name.startswith(LAND_PREFIXES):
            return {"kind": "LAND"}
        if name.startswith(INSTANT_PREFIXES):
            return {"kind": "INSTANT"}
        if name.startswith(SORCERY_PREFIXES):
            return {"kind": "SORCERY", "sorcery": True}
        # The remaining fixed-catalog cards are creatures, enchantments, or
        # artifacts. Their card-specific effects are intentionally outside this
        # change, but their permanent/sorcery-speed behavior is still enforced.
        return {"kind": "PERMANENT", "sorcery": True}

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
        elif effect.get("kind") in {"CREATURE", "PERMANENT"}:
            permanent = {
                "id": item.source,
                "controller_id": item.controller,
                "tapped": False,
            }
            if effect.get("kind") == "CREATURE":
                permanent.update({
                    "damage": 0,
                    "power": effect["power"],
                    "toughness": effect["toughness"],
                    "summoning_sick": not effect.get("haste", False),
                })
            self.state["battlefield"][item.controller].append(permanent)
            changes.append({"change_type": "ENTER_BATTLEFIELD", "target": item.source})
        return changes

    def _battlefield_permanents(self):
        """Return trigger sources with an explicit controller on every item."""
        permanents = []
        for player_id, battlefield in self.state["battlefield"].items():
            for permanent in battlefield:
                if isinstance(permanent, dict):
                    source = dict(permanent)
                    source.setdefault("controller_id", player_id)
                    permanents.append(source)
        return permanents

    def queue_trigger_event(self, event, context=None, departed_permanents=None):
        """Detect and queue RFC 8.6.1 triggers without granting priority.

        Dev 4 can call this method with ``COMBAT_DAMAGE_DEALT`` after applying
        combat damage. LTB/dies callers pass the departed permanent snapshots
        because those cards are no longer present on the battlefield.
        """
        sources = self._battlefield_permanents()
        sources.extend(departed_permanents or [])
        self.pending_triggers.extend(
            self.turn_manager.make_triggers(event, sources, context or {})
        )

    def _send_trigger_choice(self, trigger):
        seq_num = self.server.get_next_sequence_number()
        self.pending_trigger_choice = {"trigger": trigger, "seq_num": seq_num}
        self.server.send_to_player(trigger["controller_id"], {
            "type": "TRIGGER_CHOICE",
            "seq_num": seq_num,
            "trigger_id": trigger["trigger_id"],
            "source_id": trigger["source_id"],
            "effect_summary": trigger["effect_summary"],
            "requires_target": trigger["requires_target"],
            "legal_targets": trigger["legal_targets"],
        })

    def _send_trigger_order(self, player_id, triggers):
        seq_num = self.server.get_next_sequence_number()
        trigger_ids = [trigger["trigger_id"] for trigger in triggers]
        self.pending_trigger_order = {
            "player_id": player_id,
            "triggers": triggers,
            "trigger_ids": trigger_ids,
            "seq_num": seq_num,
        }
        self.server.send_to_player(player_id, {
            "type": "TRIGGER_ORDER",
            "seq_num": seq_num,
            "player_id": player_id,
            "trigger_ids": trigger_ids,
        })

    def _process_pending_triggers(self, priority_player):
        """Resolve choices/order, push triggers in APNAP order, then allow priority."""
        if not self.pending_triggers:
            self.deferred_priority_player = None
            return False
        self.deferred_priority_player = priority_player
        if self.pending_trigger_choice or self.pending_trigger_order:
            return True

        # A mandatory targeted trigger with no legal target disappears without
        # a prompt or STACK_PUSH, as required by RFC 8.6.4.
        self.pending_triggers = [
            trigger for trigger in self.pending_triggers
            if not (trigger["requires_target"] and not trigger["legal_targets"])
        ]
        for trigger in self.pending_triggers:
            needs_choice = trigger["optional"] or trigger["requires_target"]
            if needs_choice and not trigger["choice_resolved"]:
                self._send_trigger_choice(trigger)
                return True

        # AP chooses within their group first, then NAP. The groups themselves
        # remain AP then NAP so NAP triggers occupy the top of the stack.
        for controller_id in (self.state["active_player"],
                              self.turn_manager.opponent(self.state["active_player"])):
            group = [trigger for trigger in self.pending_triggers
                     if trigger["controller_id"] == controller_id]
            if len(group) == 1:
                group[0]["order_resolved"] = True
            elif len(group) >= 2 and not all(trigger["order_resolved"] for trigger in group):
                self._send_trigger_order(controller_id, group)
                return True

        for trigger in self.turn_manager.apnap_order(self.pending_triggers):
            targets = [trigger["chosen_target"]] if trigger["chosen_target"] is not None else []
            item = self.turn_manager.push(
                "TRIGGER_ABILITY", trigger["source_id"], trigger["controller_id"],
                targets, trigger["effect"]
            )
            self.server.broadcast({
                "type": "STACK_PUSH",
                "seq_num": self.server.get_next_sequence_number(),
                **item.public(),
            })
        self.pending_triggers = []
        self.deferred_priority_player = None
        self.send_personalized_state_update()
        return False

    def handle_trigger_choice_response(self, player_id, pdu):
        pending = self.pending_trigger_choice
        trigger = pending["trigger"] if pending else None
        try:
            if not pending or player_id != trigger["controller_id"] or pdu.get("seq_num") != pending["seq_num"]:
                raise GameRuleError("TRIGGER_CHOICE_INVALID", "Response does not match the pending trigger choice.")
            self.turn_manager.validate_trigger_choice(
                trigger, pdu.get("trigger_id"), pdu.get("accept"), pdu.get("chosen_target")
            )
        except GameRuleError as error:
            self.server.send_error(player_id, error.code, error.message, pdu, pdu.get("seq_num"))
            if pending:
                self.server.send_to_player(player_id, {
                    "type": "TRIGGER_CHOICE", "seq_num": pending["seq_num"],
                    "trigger_id": trigger["trigger_id"], "source_id": trigger["source_id"],
                    "effect_summary": trigger["effect_summary"],
                    "requires_target": trigger["requires_target"],
                    "legal_targets": trigger["legal_targets"],
                })
            return

        self.pending_trigger_choice = None
        if not pdu["accept"]:
            self.pending_triggers.remove(trigger)
        else:
            trigger["choice_resolved"] = True
            trigger["chosen_target"] = pdu.get("chosen_target")
        priority_player = self.deferred_priority_player
        if not self._process_pending_triggers(priority_player):
            self.grant_priority(priority_player)

    def handle_trigger_order_response(self, player_id, pdu):
        pending = self.pending_trigger_order
        try:
            if not pending or player_id != pending["player_id"] or pdu.get("seq_num") != pending["seq_num"]:
                raise GameRuleError("TRIGGER_ORDER_INVALID", "Response does not match the pending trigger order.")
            self.turn_manager.validate_trigger_order(
                pending["trigger_ids"], pdu.get("ordered_trigger_ids", [])
            )
        except GameRuleError as error:
            self.server.send_error(player_id, error.code, error.message, pdu, pdu.get("seq_num"))
            if pending:
                self.server.send_to_player(player_id, {
                    "type": "TRIGGER_ORDER", "seq_num": pending["seq_num"],
                    "player_id": player_id, "trigger_ids": pending["trigger_ids"],
                })
            return

        by_id = {trigger["trigger_id"]: trigger for trigger in pending["triggers"]}
        ordered = [by_id[trigger_id] for trigger_id in pdu["ordered_trigger_ids"]]
        for trigger in ordered:
            trigger["order_resolved"] = True
        group_positions = [index for index, trigger in enumerate(self.pending_triggers)
                           if trigger["controller_id"] == player_id]
        for index, trigger in zip(group_positions, ordered):
            self.pending_triggers[index] = trigger
        self.pending_trigger_order = None
        priority_player = self.deferred_priority_player
        if not self._process_pending_triggers(priority_player):
            self.grant_priority(priority_player)

    def notify_combat_damage(self, context=None):
        """Dev 4 integration hook: call after combat damage has been applied."""
        self.queue_trigger_event("COMBAT_DAMAGE_DEALT", context or {})
        self.grant_priority(self.state["active_player"])

    def notify_permanent_left(self, permanent, died=False):
        """Integration hook for destroy/exile/bounce/sacrifice operations."""
        event = "CREATURE_DIED" if died else "PERMANENT_LTB"
        self.queue_trigger_event(event, {"source_id": permanent.get("id")}, [dict(permanent)])

    def grant_priority(self, player_id):
        """
        name: grant_priority
        description: Issues a PRIORITY_GRANT PDU to the specified player, updating the priority holder state.
        @param: player_id (str): The player who now holds priority.
        """

        if self.check_state_based_actions():
            return
        if self._process_pending_triggers(player_id):
            self.state["priority_holder"] = None
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

        logger.debug(f"Granting priority to {player_id}: {priority_grant_pdu}")
        self.server.send_to_player(player_id, priority_grant_pdu)

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

            logger.debug(f"Regranting PRIORITY to player {player_id}: {regrant_priority_grant_pdu}")
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
            sba_changes = self.turn_manager.apply_state_based_actions()
            departed = [change["permanent"] for change in sba_changes]
            for permanent in departed:
                # Each death is a distinct event. A "whenever a creature dies"
                # ability therefore triggers once per creature, even when SBAs
                # move several creatures simultaneously.
                self.queue_trigger_event("PERMANENT_LTB", {"permanent": permanent}, [permanent])
                self.queue_trigger_event("CREATURE_DIED", {"creature": permanent}, [permanent])
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
        expected_seq = self.server.players.get(player_id, {}).get("last_seq_sent")
        if expected_seq is not None and seq != expected_seq:
            self.server.send_error(player_id, "STALE_ACTION",
                                   f"Expected sequence number {expected_seq}, but got {seq}.", pdu, seq)
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
        self.state["hand_counts"][player_id] = len(temp_hand)
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

        logger.debug(f"Broadcasting GAME_OVER: {game_over_pdu}")
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