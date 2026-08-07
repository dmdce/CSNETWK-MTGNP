"""
The manager mutates the authoritative state owned by GameEngine.  Network
I/O remains in GameEngine so this module can be unit-tested in isolation and
Dev 4 can plug combat handling into the clearly marked combat boundary.
"""

from dataclasses import dataclass, field
from itertools import count


PRIORITY_STEPS = {
    "UPKEEP", "DRAW", "PRECOMBAT_MAIN", "BEGIN_COMBAT",
    "END_OF_COMBAT", "POSTCOMBAT_MAIN", "END_STEP",
}
SORCERY_STEPS = {"PRECOMBAT_MAIN", "POSTCOMBAT_MAIN"}

NEXT_STEP = {
    "UPKEEP": "DRAW",
    "DRAW": "PRECOMBAT_MAIN",
    "PRECOMBAT_MAIN": "BEGIN_COMBAT",
    # Dev 4 owns transitions BEGIN_COMBAT through END_OF_COMBAT.
    "END_OF_COMBAT": "POSTCOMBAT_MAIN",
    "POSTCOMBAT_MAIN": "END_STEP",
    "END_STEP": "CLEANUP",
}


class GameRuleError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class StackItem:
    stack_item_id: str
    item_type: str
    source_id: str
    controller_id: str
    targets: list = field(default_factory=list)
    effect: dict = field(default_factory=dict)

    # Compatibility properties keep existing resolution code readable while
    # the public/state representation uses the RFC Section 8.3 field names.
    @property
    def source(self):
        return self.source_id

    @property
    def controller(self):
        return self.controller_id

    def public(self):
        return {
            "stack_item_id": self.stack_item_id,
            "item_type": self.item_type,
            "source_id": self.source_id,
            "targets": list(self.targets),
            "controller_id": self.controller_id,
        }


class TurnManager:
    """Pure rules state machine used by ``GameEngine`` during IN_GAME."""

    def __init__(self, state, player_ids):
        self.state = state
        self.player_ids = player_ids
        self.consecutive_passes = 0
        self.stack_items = {}
        self._stack_ids = count(1)
        self._trigger_ids = count(1)
        self.pending_trigger_decisions = {}
        self.last_draw_failed = False

    @property
    def active_player(self):
        return self.state["active_player"]

    def opponent(self, player_id):
        return self.player_ids[1] if player_id == self.player_ids[0] else self.player_ids[0]

    def begin_game(self):
        self.state["turn"] = 1
        return self.begin_turn("MULLIGAN")

    def begin_turn(self, from_phase="CLEANUP"):
        """Run no-priority Untap and enter Upkeep."""
        self.state["phase"] = "UNTAP"
        self.state["priority_holder"] = None
        self.state["land_played_this_turn"] = False
        for permanent in self.state["battlefield"][self.active_player]:
            if isinstance(permanent, dict):
                permanent["tapped"] = False
                permanent["summoning_sick"] = False
        self.state["phase"] = "UPKEEP"
        return [(from_phase, "UNTAP"), ("UNTAP", "UPKEEP")]

    def pass_priority(self, player_id):
        if self.state.get("priority_holder") != player_id:
            raise GameRuleError("NOT_YOUR_PRIORITY", "You do not currently hold priority.")
        self.consecutive_passes += 1
        if self.consecutive_passes == 1:
            self.state["priority_holder"] = self.opponent(player_id)
            return "TRANSFER"
        self.consecutive_passes = 0
        self.state["priority_holder"] = None
        return "RESOLVE" if self.state["stack"] else "ADVANCE"

    def action_taken(self, player_id):
        # Casting/activating/playing a land breaks a consecutive-pass pair.
        self.consecutive_passes = 0
        self.state["priority_holder"] = player_id

    def advance_priority_step(self):
        old = self.state["phase"]
        if old not in NEXT_STEP:
            # Combat progression is deliberately delegated to Dev 4.
            raise GameRuleError("ILLEGAL_ACTION", "Combat step must be advanced by the combat engine.")
        new = NEXT_STEP[old]
        self.state["phase"] = new
        self.state["priority_holder"] = None
        if new == "DRAW" and self.state["turn"] != 1:
            self.last_draw_failed = not self.draw_card(self.active_player)
        else:
            self.last_draw_failed = False
        return old, new

    def begin_combat_step(self):
        """Mutates state for entering BEGIN_COMBAT and collects phase triggers.

        Resets pass count, clears floating mana, and queues APNAP combat triggers.
        Assumes phase string was already set to "BEGIN_COMBAT" by advance_priority_step().
        """
        self.consecutive_passes = 0
        self.state["priority_holder"] = None

        if "mana_pool" in self.state:
            for pid in self.player_ids:
                self.state["mana_pool"][pid] = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}

        all_permanents = []
        for zone in self.state["battlefield"].values():
            all_permanents.extend([p for p in zone if isinstance(p, dict)])

        raw_triggers = self.make_triggers("BEGIN_COMBAT", all_permanents)
        ordered_triggers = self.apnap_order(raw_triggers)

        for trg in ordered_triggers:
            self.push(
                item_type="TRIGGER",
                source=trg["source_id"],
                controller=trg["controller_id"],
                effect=trg.get("effect", {})
            )

        return "PRECOMBAT_MAIN", "BEGIN_COMBAT"

    def draw_card(self, player_id):
        library = self.state["libraries"][player_id]
        if not library:
            # TODO: Route to a behavior that triggers the DECK_EMPTY state for the player
            raise GameRuleError("DECK_EMPTY", "The player has no cards left in their library.")
        self.state["hand"][player_id].append(library.pop())
        self.state["hand_counts"][player_id] = len(self.state["hand"][player_id])
        return True

    def finish_cleanup(self):
        if len(self.state["hand"][self.active_player]) > 7:
            raise GameRuleError("ILLEGAL_ACTION", "The active player must discard to seven first.")
        for battlefield in self.state["battlefield"].values():
            for permanent in battlefield:
                if isinstance(permanent, dict):
                    permanent["damage"] = 0
                    permanent.pop("until_end_of_turn", None)
        old_active = self.active_player
        self.state["turn"] += 1
        self.state["active_player"] = self.opponent(old_active)
        return self.begin_turn()

    def is_sorcery_speed(self, player_id):
        return (player_id == self.active_player
                and self.state["phase"] in SORCERY_STEPS
                and not self.state["stack"])

    def play_land(self, player_id, card_id):
        if not self.is_sorcery_speed(player_id):
            raise GameRuleError("WRONG_PHASE", "A land may only be played during your main phase with an empty stack.")
        if self.state.get("land_played_this_turn"):
            raise GameRuleError("ILLEGAL_ACTION", "Only one land may be played each turn.")
        if card_id not in self.state["hand"][player_id]:
            raise GameRuleError("ILLEGAL_ACTION", "The selected card is not in your hand.")
        if not str(card_id).lower().startswith(("mountain", "island", "swamp", "forest", "plains")):
            raise GameRuleError("ILLEGAL_ACTION", "The selected card is not a land.")
        self.state["hand"][player_id].remove(card_id)
        self.state["hand_counts"][player_id] = len(self.state["hand"][player_id])
        self.state["battlefield"][player_id].append({"id": card_id, "tapped": False})
        self.state["land_played_this_turn"] = True
        self.action_taken(player_id)

    def pay_mana(self, player_id, mana_payment):
        """Validate and tap declared mana sources atomically.

        The RFC example uses colour totals while the game state stores lands.
        Basic-land names therefore provide the authoritative available sources.
        """
        if not isinstance(mana_payment, dict) or any(
                not isinstance(value, int) or value < 0 for value in mana_payment.values()):
            raise GameRuleError("INSUFFICIENT_MANA", "mana_payment must contain non-negative integer totals.")
        colour_names = {"W": "plains", "U": "island", "B": "swamp", "R": "mountain", "G": "forest"}
        untapped = [p for p in self.state["battlefield"][player_id]
                    if isinstance(p, dict) and not p.get("tapped")]
        selected = []
        # Reserve coloured sources first so a generic payment cannot consume a
        # land that is required by a later coloured component.
        ordered_payment = sorted(mana_payment.items(), key=lambda entry: entry[0] == "X")
        for colour, amount in ordered_payment:
            if colour != "X":
                land_name = colour_names.get(colour)
                if land_name is None:
                    raise GameRuleError("INSUFFICIENT_MANA", "Unknown mana colour in mana_payment.")
                candidates = [p for p in untapped if p not in selected
                              and str(p.get("id", "")).lower().startswith(land_name)]
            else:
                candidates = [p for p in untapped if p not in selected]
            if len(candidates) < amount:
                raise GameRuleError("INSUFFICIENT_MANA", "The declared mana payment cannot be satisfied.")
            selected.extend(candidates[:amount])
        for source in selected:
            source["tapped"] = True

    def push(self, item_type, source, controller, targets=None, effect=None):
        item = StackItem(f"stk_{next(self._stack_ids):04d}", item_type, source,
                         controller, targets or [], effect or {})
        self.stack_items[item.stack_item_id] = item
        self.state["stack"].append(item.public())
        self.action_taken(controller)
        return item

    def pop(self):
        public = self.state["stack"].pop()
        return self.stack_items.pop(public["stack_item_id"])

    def target_is_legal(self, target):
        if target in self.player_ids:
            return True
        return (any(item["stack_item_id"] == target for item in self.state["stack"])
                or any(isinstance(p, dict) and p.get("id") == target
                       for zone in self.state["battlefield"].values() for p in zone))

    def apply_state_based_actions(self):
        changes = []
        changed = True
        while changed:
            changed = False
            for player_id in self.player_ids:
                survivors = []
                for permanent in self.state["battlefield"][player_id]:
                    if isinstance(permanent, dict) and "toughness" in permanent and (
                            permanent["toughness"] <= 0
                            or permanent.get("damage", 0) >= permanent["toughness"]):
                        card_id = permanent.get("id")
                        graveyard_owner = permanent.get("owner_id", player_id)
                        self.state["graveyard"][graveyard_owner].append(card_id)
                        permanent_snapshot = dict(permanent)
                        permanent_snapshot.setdefault("controller_id", player_id)
                        changes.append({
                            "change_type": "DESTROY",
                            "target": card_id,
                            "controller_id": permanent.get("controller_id", player_id),
                            "permanent": permanent_snapshot,
                        })
                        changed = True
                    else:
                        survivors.append(permanent)
                self.state["battlefield"][player_id] = survivors
        return changes

    def make_triggers(self, event, permanents, event_context=None):
        """Detect catalog-provided triggers matching a game event.

        A permanent may declare ``event`` as a string or ``events`` as a list.
        This keeps the detector independent of the eventual shared card
        catalog while supporting every event required by RFC 8.6.1.
        """
        triggers = []
        event_context = event_context or {}
        event_aliases = {
            "PERMANENT_ETB": {"PERMANENT_ETB", "ETB"},
            "PERMANENT_LTB": {"PERMANENT_LTB", "LTB"},
            "CREATURE_DIED": {"CREATURE_DIED", "DIES"},
            "SPELL_CAST": {"SPELL_CAST", "SPELL_ABILITY_CAST", "CAST"},
            "ABILITY_CAST": {"ABILITY_CAST", "SPELL_ABILITY_CAST", "CAST"},
            "CARD_DRAWN": {"CARD_DRAWN", "DRAW"},
            "STEP_PHASE_BEGIN": {
                "STEP_PHASE_BEGIN", "PHASE_BEGIN", event_context.get("phase"),
                f"BEGIN_{event_context.get('phase')}" if event_context.get("phase") else None,
            },
            "COMBAT_DAMAGE_DEALT": {"COMBAT_DAMAGE_DEALT", "COMBAT_DAMAGE"},
        }
        matching_events = event_aliases.get(event, {event})
        for permanent in permanents:
            for ability in permanent.get("triggered_abilities", []):
                accepted_events = ability.get("events", [ability.get("event")])
                if isinstance(accepted_events, str):
                    accepted_events = [accepted_events]
                if matching_events.intersection(accepted_events):
                    triggers.append({
                        "trigger_id": f"trg_{next(self._trigger_ids):04d}",
                        "source_id": permanent.get("id"),
                        "controller_id": permanent.get("controller_id"),
                        "optional": ability.get("optional", False),
                        "requires_target": ability.get("requires_target", False),
                        "effect_summary": ability.get("effect_summary", "Triggered ability"),
                        "legal_targets": list(ability.get("legal_targets", event_context.get("legal_targets", []))),
                        "effect": ability.get("effect", {}),
                        "chosen_target": None,
                        "choice_resolved": False,
                        "order_resolved": False,
                    })
        return triggers

    def apnap_order(self, triggers):
        ap = [t for t in triggers if t["controller_id"] == self.active_player]
        nap = [t for t in triggers if t["controller_id"] != self.active_player]
        return ap + nap

    @staticmethod
    def validate_trigger_order(expected_ids, ordered_ids):
        if (not isinstance(ordered_ids, list)
                or any(not isinstance(trigger_id, str) for trigger_id in ordered_ids)
                or len(expected_ids) != len(ordered_ids)
                or sorted(expected_ids) != sorted(ordered_ids)):
            raise GameRuleError("TRIGGER_ORDER_INVALID", "Each pending trigger must appear exactly once.")

    @staticmethod
    def validate_trigger_choice(trigger, trigger_id, accept, chosen_target):
        if trigger is None or trigger.get("trigger_id") != trigger_id or not isinstance(accept, bool):
            raise GameRuleError("TRIGGER_CHOICE_INVALID", "Response does not match the pending trigger choice.")
        if not trigger.get("optional") and not accept:
            raise GameRuleError("TRIGGER_CHOICE_INVALID", "A mandatory trigger cannot be declined.")
        if accept and trigger.get("requires_target"):
            if chosen_target not in trigger.get("legal_targets", []):
                raise GameRuleError("TRIGGER_CHOICE_INVALID", "chosen_target is not legal for this trigger.")
