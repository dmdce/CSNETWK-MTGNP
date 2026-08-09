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
        self.state["pending_damage_orders"] = {}
        self.state["damage_orders"] = {}

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

        # Reset combat tracking structures
        self.state["declared_attackers"] = []
        self.state["declared_blockers"] = []
        self.state["pending_damage_orders"] = {}
        self.state["damage_orders"] = {}

        # Untap and clear creature combat flags across all battlefields
        for pid in self.player_ids:
            for permanent in self.state["battlefield"].get(pid, []):
                if isinstance(permanent, dict):
                    # Untap active player's permanents & remove summoning sickness
                    if pid == self.active_player:
                        permanent["tapped"] = False
                        permanent["summoning_sick"] = False

                    # Clear combat status for all players' permanents
                    permanent.pop("attacking", None)
                    permanent.pop("blocking", None)

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
        if new == "DRAW":
            self.last_draw_failed = not self.draw_card(self.active_player)
        else:
            self.last_draw_failed = False
        return old, new

    def begin_combat(self):
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
                item_type="TRIGGER_ABILITY",
                source=trg["source_id"],
                controller=trg["controller_id"],
                effect=trg.get("effect", {})
            )

        return "PRECOMBAT_MAIN", "BEGIN_COMBAT"

    def declare_attackers(self, player_id, attackers):
        """
        Validates and applies declared attackers according to MTGNP v1.0 Section 9.3.
        """
        if self.state.get("phase") != "DECLARE_ATTACKERS":
            raise GameRuleError("WRONG_PHASE", "Cannot declare attackers outside of DECLARE_ATTACKERS step.")

        if player_id != self.active_player:
            raise GameRuleError("NOT_YOUR_PRIORITY", "Only the active player can declare attackers.")

        if not isinstance(attackers, list):
            raise GameRuleError("ILLEGAL_ACTION", "'attackers' must be a list.")

        ap_battlefield = self.state.get("battlefield", {}).get(player_id, [])
        valid_attackers = []

        # Validate each attacker object according to Section 10.2.15 schema
        for attacker in attackers:
            if not isinstance(attacker, dict) or "creature_id" not in attacker or "target" not in attacker:
                raise GameRuleError("ILLEGAL_ACTION", "Each attacker must specify creature_id and target.")

            attacker_id = attacker["creature_id"]
            perm = next((c for c in ap_battlefield if c.get("id") == attacker_id), None)

            if not perm:
                raise GameRuleError("ILLEGAL_ACTION", f"Creature {attacker_id} is not on your battlefield.")

            if perm.get("tapped", False):
                raise GameRuleError("ILLEGAL_ACTION", f"Creature {attacker_id} is already tapped.")

            if perm.get("summoning_sick", False) and not perm.get("haste", False):
                raise GameRuleError("ILLEGAL_ACTION", f"Creature {attacker_id} has summoning sickness.")

            valid_attackers.append(attacker)

        # Apply state changes
        declared_attacker_ids = []
        for attacker in valid_attackers:
            attacker_id = attacker["creature_id"]
            perm = next(c for c in ap_battlefield if c.get("id") == attacker_id)
            if not perm.get("vigilance", False):
                perm["tapped"] = True
            perm["attacking"] = True
            declared_attacker_ids.append(attacker_id)

        self.state["declared_attackers"] = valid_attackers

        # Section 9.3: If no attackers declared, skip directly to END_OF_COMBAT
        if not declared_attacker_ids:
            self.state["phase"] = "END_OF_COMBAT"
        else:
            self.state["phase"] = "DECLARE_BLOCKERS"

        self.state["priority_holder"] = self.active_player
        return declared_attacker_ids

    def declare_blockers(self, player_id, blockers):
        """
        Validates and applies declared blockers from the non-active player.
        Blocking does NOT tap the blocker.
        """
        if self.state.get("phase") != "DECLARE_BLOCKERS":
            raise GameRuleError("WRONG_PHASE", "Cannot declare blockers outside of DECLARE_BLOCKERS step.")

        if player_id == self.active_player:
            raise GameRuleError("NOT_YOUR_PRIORITY", "Only the non-active player (defender) can declare blockers.")

        if not isinstance(blockers, list):
            raise GameRuleError("ILLEGAL_ACTION", "'blockers' must be a list.")

        nap_battlefield = self.state.get("battlefield", {}).get(player_id, [])
        declared_attackers = self.state.get("declared_attackers", [])
        valid_attacker_ids = {
            a["creature_id"] if isinstance(a, dict) else a for a in declared_attackers
        }

        validated_blockers = []
        assigned_blockers = set()

        for entry in blockers:
            if not isinstance(entry, dict) or "blocker_id" not in entry or "attacker_id" not in entry:
                raise GameRuleError("ILLEGAL_ACTION", "Each blocker must specify blocker_id and attacker_id.")

            blocker_id = entry["blocker_id"]
            attacker_id = entry["attacker_id"]

            # ENFORCE: One attacker per blocker
            if blocker_id in assigned_blockers:
                raise GameRuleError("ILLEGAL_ACTION", f"Creature {blocker_id} is already blocking an attacker.")

            # FIX: Check blocker_id against NAP battlefield
            perm = next((c for c in nap_battlefield if isinstance(c, dict) and c.get("id") == blocker_id), None)
            if not perm:
                raise GameRuleError("ILLEGAL_ACTION", f"Creature {blocker_id} is not on your battlefield.")

            # Tapped creatures cannot block
            if perm.get("tapped", False):
                raise GameRuleError("ILLEGAL_ACTION", f"Creature {blocker_id} is tapped and cannot block.")

            # Attacker must be valid
            if attacker_id not in valid_attacker_ids:
                raise GameRuleError("ILLEGAL_ACTION", f"Creature {attacker_id} is not an active attacker.")

            assigned_blockers.add(blocker_id)

            # Note: perm["tapped"] is deliberately NOT set to True (blocking does not tap)
            perm["blocking"] = attacker_id
            validated_blockers.append({"blocker_id": blocker_id, "attacker_id": attacker_id})

        self.state["declared_blockers"] = validated_blockers

        # Group blockers by attacker to check for multiple blockers
        attacker_blockers = {}
        for entry in validated_blockers:
            attacker_blockers.setdefault(entry["attacker_id"], []).append(entry["blocker_id"])

        multiply_blocked = {
            att_id: b_list for att_id, b_list in attacker_blockers.items() if len(b_list) >= 2
        }

        # Transition to ASSIGN_DAMAGE_ORDER if 2+ blockers block an attacker, otherwise COMBAT_DAMAGE
        if multiply_blocked:
            self.state["phase"] = "ASSIGN_DAMAGE_ORDER"
            self.state["pending_damage_orders"] = multiply_blocked
            self.state["damage_orders"] = {}
        else:
            self.check_and_advance_combat_damage_phase()

        self.state["priority_holder"] = self.active_player
        return validated_blockers

    def assign_damage_order(self, player_id, attacker_id, ordered_blocker_ids):
        """
        Active player sets the ordering of 2+ blockers for a specific attacker.
        """
        if self.state.get("phase") != "ASSIGN_DAMAGE_ORDER":
            raise GameRuleError("WRONG_PHASE", "Cannot assign damage order outside ASSIGN_DAMAGE_ORDER step.")

        if player_id != self.active_player:
            raise GameRuleError("NOT_YOUR_PRIORITY", "Only the active player can assign damage ordering.")

        pending = self.state.get("pending_damage_orders", {})
        if attacker_id not in pending:
            raise GameRuleError("ILLEGAL_ACTION", f"Attacker {attacker_id} does not require damage ordering.")

        expected_blockers = set(pending[attacker_id])
        if set(ordered_blocker_ids) != expected_blockers or len(ordered_blocker_ids) != len(expected_blockers) or len(set(ordered_blocker_ids)) != len(ordered_blocker_ids):
            raise GameRuleError("ILLEGAL_ACTION", "Damage order must include every assigned blocker exactly once.")

        # Record the ordered blockers
        self.state.setdefault("damage_orders", {})[attacker_id] = ordered_blocker_ids
        del pending[attacker_id]

        # Advance phase once all multiply-blocked attackers are resolved
        if not pending:
            self.check_and_advance_combat_damage_phase()

        return ordered_blocker_ids

    def get_combat_keywords(self, creature):
        """
        Internal helper to extract normalized combat keywords for a creature.
        """
        if not isinstance(creature, dict):
            return set()
        keywords = set(creature.get("keywords", []))
        if creature.get("first_strike"):
            keywords.add("first_strike")
        if creature.get("double_strike"):
            keywords.add("double_strike")
        return keywords

    def has_first_or_double_strike(self, creature):
        """
        Helper to check if a creature has first or double strike.
        """
        kw = self.get_combat_keywords(creature)
        return "first_strike" in kw or "double_strike" in kw

    def deals_damage_in_step(self, creature, is_first_strike):
        """
        Returns True if the creature is eligible to deal combat damage in the current step.
        - First Strike step: deals damage if it has first_strike or double_strike.
        - Regular step: deals damage if it lacks first_strike, OR has double_strike.
        """
        kw = self.get_combat_keywords(creature)
        has_fs = "first_strike" in kw or "double_strike" in kw
        has_ds = "double_strike" in kw

        return has_fs if is_first_strike else (not has_fs or has_ds)

    def check_and_advance_combat_damage_phase(self):
        """
        Determines whether combat proceeds to FIRST_STRIKE_DAMAGE or COMBAT_DAMAGE
        """
        ap, nap = self.active_player, self.opponent(self.active_player)

        ap_bf = {c["id"]: c for c in self.state.get("battlefield", {}).get(ap, []) if isinstance(c, dict)}
        nap_bf = {c["id"]: c for c in self.state.get("battlefield", {}).get(nap, []) if isinstance(c, dict)}

        declared_attackers = self.state.get("declared_attackers", [])
        declared_blockers = self.state.get("declared_blockers", [])

        att_ids = {a["creature_id"] if isinstance(a, dict) else a for a in declared_attackers}
        blocker_ids = {b["blocker_id"] for b in declared_blockers if isinstance(b, dict)}

        has_fs = (
                any(self.has_first_or_double_strike(ap_bf[cid]) for cid in att_ids if cid in ap_bf) or
                any(self.has_first_or_double_strike(nap_bf[cid]) for cid in blocker_ids if cid in nap_bf)
        )

        self.state["phase"] = "FIRST_STRIKE_DAMAGE" if has_fs else "COMBAT_DAMAGE"
        self.state["priority_holder"] = self.active_player
        return self.state["phase"]

    def resolve_combat_damage_step(self, is_first_strike=False):
        """
        Applies damage for either the First Strike or regular Combat Damage step,
        evaluates SBAs, and moves dead creatures to the graveyard.
        """
        ap, nap = self.active_player, self.opponent(self.active_player)

        ap_bf_list = self.state.get("battlefield", {}).get(ap, [])
        nap_bf_list = self.state.get("battlefield", {}).get(nap, [])

        ap_bf = {c["id"]: c for c in ap_bf_list if isinstance(c, dict)}
        nap_bf = {c["id"]: c for c in nap_bf_list if isinstance(c, dict)}

        declared_attackers = self.state.get("declared_attackers", [])
        declared_blockers = self.state.get("declared_blockers", [])
        damage_orders = self.state.get("damage_orders", {})

        # Map attacker_id -> list of blocker_ids
        attacker_to_blockers = {}
        for entry in declared_blockers:
            if isinstance(entry, dict):
                attacker_to_blockers.setdefault(entry["attacker_id"], []).append(entry["blocker_id"])

        damage_events = []

        for att_entry in declared_attackers:
            att_id = att_entry["creature_id"] if isinstance(att_entry, dict) else att_entry
            attacker = ap_bf.get(att_id)
            if not attacker:
                continue

            attacker_can_damage = self.deals_damage_in_step(attacker, is_first_strike)
            att_power = max(0, attacker.get("power", 0))
            blocker_ids = attacker_to_blockers.get(att_id, [])

            # --- UNBLOCKED ATTACKER ---
            if not blocker_ids:
                if attacker_can_damage:
                    self.state["life_totals"][nap] = self.state["life_totals"].get(nap, 20) - att_power
                    damage_events.append({
                        "source_id": att_id,
                        "target_id": nap,
                        "amount": att_power,
                        "is_player": True
                    })
                continue

            # --- BLOCKED ATTACKER ---
            ordered_ids = damage_orders.get(att_id, blocker_ids)
            remaining_power = att_power
            active_blockers = [nap_bf[bid] for bid in ordered_ids if bid in nap_bf]

            for i, blocker in enumerate(active_blockers):
                # 1. Blocker deals damage to Attacker
                if self.deals_damage_in_step(blocker, is_first_strike):
                    b_power = max(0, blocker.get("power", 0))
                    attacker["damage"] = attacker.get("damage", 0) + b_power
                    damage_events.append({
                        "source_id": blocker["id"],
                        "target_id": att_id,
                        "amount": b_power,
                        "is_player": False
                    })

                # 2. Attacker deals damage to Blocker
                if attacker_can_damage and remaining_power > 0:
                    b_toughness = max(0, blocker.get("toughness", 0))
                    b_damage = blocker.get("damage", 0)

                    # Lethal damage needed = toughness minus damage already marked
                    lethal_needed = max(0, b_toughness - b_damage)
                    is_last_blocker = (i == len(active_blockers) - 1)

                    assigned = remaining_power if is_last_blocker else min(remaining_power, lethal_needed)
                    if assigned > 0:
                        blocker["damage"] = b_damage + assigned
                        remaining_power -= assigned
                        damage_events.append({
                            "source_id": att_id,
                            "target_id": blocker["id"],
                            "amount": assigned,
                            "is_player": False
                        })

        # --- STATE-BASED ACTIONS (SBAs) ---
        creatures_died = []
        for owner_id, bf in [(ap, ap_bf_list), (nap, nap_bf_list)]:
            dead_creatures = [
                c for c in bf
                if isinstance(c, dict) and c.get("damage", 0) >= c.get("toughness", 0) > 0
            ]
            for dead in dead_creatures:
                bf.remove(dead)
                creatures_died.append(dead["id"])
                self.state.setdefault("graveyard", {}).setdefault(owner_id, []).append(dead)

        return {
            "damage_events": damage_events,
            "life_totals": dict(self.state.get("life_totals", {})),
            "creatures_died": creatures_died
        }

    def clear_combat_state(self):
        """
        Clears attacker/blocker assignments and marked damage from all battlefield permanents.
        """
        # Clear combat declaration tracking
        self.state["attackers"] = []
        self.state["blockers"] = []
        self.state["damage_orders"] = {}

        # Clear combat damage marked on permanents across all players
        battlefield = self.state.get("battlefield", {})
        for player_id, permanents in battlefield.items():
            for card in permanents:
                if isinstance(card, dict) and "damage" in card:
                    card["damage"] = 0

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