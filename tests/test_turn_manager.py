import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from turn_manager import GameRuleError, TurnManager
from engine import GameEngine

def game_state():
    return {
        "turn": 0,
        "phase": "MULLIGAN",
        "active_player": "p1",
        "priority_holder": None,
        "life_totals": {"p1": 20, "p2": 20},
        "hand": {"p1": ["mountain_001", "shock_001"], "p2": []},
        "hand_counts": {"p1": 2, "p2": 0},
        "libraries": {"p1": ["draw_001", "draw_002"], "p2": ["draw_003"]},
        "battlefield": {"p1": [], "p2": []},
        "graveyard": {"p1": [], "p2": []},
        "stack": [],
        "land_played_this_turn": False,
    }

class TurnManagerTests(unittest.TestCase):
    def setUp(self):
        self.state = game_state()
        self.manager = TurnManager(self.state, ["p1", "p2"])

    def test_begin_game_runs_untap_and_enters_upkeep(self):
        transitions = self.manager.begin_game()
        self.assertEqual([("MULLIGAN", "UNTAP"), ("UNTAP", "UPKEEP")], transitions)
        self.assertEqual(1, self.state["turn"])
        self.assertEqual("UPKEEP", self.state["phase"])

    def test_first_turn_draw_is_skipped(self):
        self.manager.begin_game()
        before = list(self.state["hand"]["p1"])
        self.assertEqual(("UPKEEP", "DRAW"), self.manager.advance_priority_step())
        self.assertEqual(before, self.state["hand"]["p1"])

    def test_draw_card_moves_top_card_and_updates_hand_count(self):
        self.assertTrue(self.manager.draw_card("p1"))
        self.assertEqual(["draw_001"], self.state["libraries"]["p1"])
        self.assertEqual("draw_002", self.state["hand"]["p1"][-1])
        self.assertEqual(3, self.state["hand_counts"]["p1"])

    def test_draw_card_reports_empty_library_without_mutating_hand(self):
        self.state["libraries"]["p1"] = []
        hand_before = list(self.state["hand"]["p1"])

        self.assertFalse(self.manager.draw_card("p1"))
        self.assertEqual(hand_before, self.state["hand"]["p1"])
        self.assertEqual(2, self.state["hand_counts"]["p1"])

    def test_priority_transfers_then_advances_after_two_passes(self):
        self.manager.begin_game()
        self.state["priority_holder"] = "p1"
        self.assertEqual("TRANSFER", self.manager.pass_priority("p1"))
        self.assertEqual("p2", self.state["priority_holder"])
        self.assertEqual("ADVANCE", self.manager.pass_priority("p2"))

    def test_nonempty_stack_resolves_lifo_after_two_passes(self):
        self.manager.begin_game()
        first = self.manager.push("SPELL", "shock_001", "p1", ["p2"])
        second = self.manager.push("SPELL", "counterspell_001", "p1", [first.stack_item_id])
        self.state["priority_holder"] = "p1"
        self.manager.pass_priority("p1")
        self.assertEqual("RESOLVE", self.manager.pass_priority("p2"))
        self.assertEqual(second.stack_item_id, self.manager.pop().stack_item_id)

    def test_stack_uses_required_public_field_names(self):
        item = self.manager.push("SPELL", "shock_001", "p1", ["p2"])
        self.assertEqual({
            "stack_item_id", "item_type", "source_id", "controller_id", "targets"
        }, set(item.public()))

    def test_land_play_is_sorcery_speed_and_once_per_turn(self):
        self.manager.begin_game()
        self.state["phase"] = "PRECOMBAT_MAIN"
        self.manager.play_land("p1", "mountain_001")
        self.assertTrue(self.state["land_played_this_turn"])
        with self.assertRaises(GameRuleError) as error:
            self.manager.play_land("p1", "shock_001")
        self.assertEqual("ILLEGAL_ACTION", error.exception.code)

    def test_mana_payment_is_atomic(self):
        lands = [
            {"id": "mountain_001", "tapped": False},
            {"id": "mountain_002", "tapped": False},
        ]
        self.state["battlefield"]["p1"] = lands
        with self.assertRaises(GameRuleError) as error:
            self.manager.pay_mana("p1", {"R": 3})
        self.assertEqual("INSUFFICIENT_MANA", error.exception.code)
        self.assertFalse(any(land["tapped"] for land in lands))
        self.manager.pay_mana("p1", {"R": 2})
        self.assertTrue(all(land["tapped"] for land in lands))

    def test_cleanup_clears_damage_and_switches_active_player(self):
        self.manager.begin_game()
        self.state["phase"] = "CLEANUP"
        self.state["battlefield"]["p1"] = [{"id": "bear_001", "damage": 2, "tapped": True}]
        transitions = self.manager.finish_cleanup()
        self.assertEqual("p2", self.state["active_player"])
        self.assertEqual(2, self.state["turn"])
        self.assertEqual(0, self.state["battlefield"]["p1"][0]["damage"])
        self.assertEqual(("CLEANUP", "UNTAP"), transitions[0])

    def test_sbas_repeat_until_all_lethal_creatures_are_removed(self):
        self.state["battlefield"]["p1"] = [
            {"id": "a", "toughness": 2, "damage": 2},
            {"id": "b", "toughness": 0, "damage": 0},
        ]
        changes = self.manager.apply_state_based_actions()
        self.assertEqual([], self.state["battlefield"]["p1"])
        self.assertEqual(["a", "b"], self.state["graveyard"]["p1"])
        self.assertEqual(2, len(changes))

    def test_apnap_trigger_order_and_validation(self):
        triggers = [
            {"trigger_id": "n1", "controller_id": "p2"},
            {"trigger_id": "a1", "controller_id": "p1"},
        ]
        self.assertEqual(["a1", "n1"], [t["trigger_id"] for t in self.manager.apnap_order(triggers)])
        with self.assertRaises(GameRuleError) as error:
            self.manager.validate_trigger_order(["a1", "a2"], ["a1", "a1"])
        self.assertEqual("TRIGGER_ORDER_INVALID", error.exception.code)

    def test_trigger_detection_supports_required_event_aliases(self):
        permanent = {
            "id": "watcher_001",
            "controller_id": "p1",
            "triggered_abilities": [{"event": "DIES", "effect": {"kind": "DRAW"}}],
        }
        triggers = self.manager.make_triggers("CREATURE_DIED", [permanent])
        self.assertEqual(1, len(triggers))
        self.assertEqual("watcher_001", triggers[0]["source_id"])


class FakeServer:
    def __init__(self):
        self.phase = "IN_GAME"
        self.seq_num = 0
        self.players = {
            "p1": {"status": "CONNECTED", "last_seq_sent": None},
            "p2": {"status": "CONNECTED", "last_seq_sent": None},
        }
        self.sent = []
        self.broadcasts = []
        self.errors = []

    def get_next_sequence_number(self):
        self.seq_num += 1
        return self.seq_num

    def send_to_player(self, player_id, pdu):
        self.sent.append((player_id, pdu))
        self.players[player_id]["last_seq_sent"] = pdu.get("seq_num")

    def broadcast(self, pdu):
        self.broadcasts.append(pdu)

    def send_error(self, player_id, code, message, rejected_action=None, seq=None):
        self.errors.append((player_id, code, message, rejected_action, seq))


class EngineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.engine = GameEngine(self.server)
        self.engine.player_ids = ["p1", "p2"]
        self.engine.state = game_state()
        self.engine.state["phase"] = "PRECOMBAT_MAIN"
        self.engine.turn_manager = TurnManager(self.engine.state, self.engine.player_ids)
        self.engine.priority_sequence = 7

    def test_land_play_does_not_require_current_priority(self):
        self.engine.state["priority_holder"] = "p2"
        self.engine.handle_play_land("p1", {
            "type": "PLAY_LAND", "seq_num": 7, "card_id": "mountain_001"
        })
        self.assertTrue(self.engine.state["land_played_this_turn"])
        self.assertEqual("p1", self.engine.state["priority_holder"])
        self.assertEqual([], self.server.errors)

    def test_optional_trigger_blocks_priority_until_response(self):
        self.engine.state["battlefield"]["p1"] = [{
            "id": "watcher_001",
            "controller_id": "p1",
            "triggered_abilities": [{
                "event": "DRAW", "optional": True,
                "effect_summary": "You may gain 1 life.",
                "effect": {"kind": "LIFE_GAIN", "amount": 1},
            }],
        }]
        self.engine.queue_trigger_event("CARD_DRAWN", {"player_id": "p1"})
        self.engine.grant_priority("p1")
        choice = self.server.sent[-1][1]
        self.assertEqual("TRIGGER_CHOICE", choice["type"])
        self.assertIsNone(self.engine.state["priority_holder"])

        self.engine.handle_trigger_choice_response("p1", {
            "type": "TRIGGER_CHOICE_RESPONSE",
            "seq_num": choice["seq_num"],
            "trigger_id": choice["trigger_id"],
            "accept": False,
        })
        self.assertEqual("PRIORITY_GRANT", self.server.sent[-1][1]["type"])
        self.assertEqual([], self.engine.state["stack"])

    def test_invalid_trigger_choice_reports_specific_error(self):
        self.engine.state["battlefield"]["p1"] = [{
            "id": "watcher_001", "controller_id": "p1",
            "triggered_abilities": [{
                "event": "ETB", "requires_target": True,
                "legal_targets": ["p2"], "effect": {"kind": "DAMAGE"},
            }],
        }]
        self.engine.queue_trigger_event("PERMANENT_ETB")
        self.engine.grant_priority("p1")
        choice = self.server.sent[-1][1]
        self.engine.handle_trigger_choice_response("p1", {
            "type": "TRIGGER_CHOICE_RESPONSE", "seq_num": choice["seq_num"],
            "trigger_id": choice["trigger_id"], "accept": True,
            "chosen_target": "not-a-target",
        })
        self.assertEqual("TRIGGER_CHOICE_INVALID", self.server.errors[-1][1])
        self.assertEqual("TRIGGER_CHOICE", self.server.sent[-1][1]["type"])

    def test_activated_ability_mana_failure_is_atomic(self):
        source = {
            "id": "artifact_001", "tapped": False,
            "abilities": [{"kind": "ABILITY"}],
        }
        mountain = {"id": "mountain_002", "tapped": False}
        self.engine.state["battlefield"]["p1"] = [source, mountain]
        self.engine.state["priority_holder"] = "p1"
        self.engine.handle_activate_ability("p1", {
            "type": "ACTIVATE_ABILITY", "seq_num": 7,
            "source_id": "artifact_001", "ability_index": 0,
            "targets": [], "mana_payment": {"R": 2},
            "cost_payment": {"tap": True},
        })
        self.assertEqual("INSUFFICIENT_MANA", self.server.errors[-1][1])
        self.assertFalse(source["tapped"])
        self.assertFalse(mountain["tapped"])

    def test_two_simultaneous_triggers_require_order_before_priority(self):
        self.engine.state["battlefield"]["p1"] = [{
            "id": "watcher_001", "controller_id": "p1",
            "triggered_abilities": [
                {"event": "UPKEEP", "effect": {"kind": "FIRST"}},
                {"event": "UPKEEP", "effect": {"kind": "SECOND"}},
            ],
        }]
        self.engine.queue_trigger_event("STEP_PHASE_BEGIN", {"phase": "UPKEEP"})
        self.engine.grant_priority("p1")
        order = self.server.sent[-1][1]
        self.assertEqual("TRIGGER_ORDER", order["type"])
        self.assertFalse(any(pdu["type"] == "PRIORITY_GRANT" for _, pdu in self.server.sent))

        reversed_ids = list(reversed(order["trigger_ids"]))
        effects_by_trigger = {
            trigger["trigger_id"]: trigger["effect"]["kind"]
            for trigger in self.engine.pending_triggers
        }
        self.engine.handle_trigger_order_response("p1", {
            "type": "TRIGGER_ORDER_RESPONSE",
            "seq_num": order["seq_num"],
            "ordered_trigger_ids": reversed_ids,
        })
        actual_effect_order = [
            self.engine.turn_manager.stack_items[item["stack_item_id"]].effect["kind"]
            for item in self.engine.state["stack"]
        ]
        self.assertEqual([effects_by_trigger[trigger_id] for trigger_id in reversed_ids],
                         actual_effect_order)
        self.assertEqual("PRIORITY_GRANT", self.server.sent[-1][1]["type"])


if __name__ == "__main__":
    unittest.main()
