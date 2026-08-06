import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from turn_manager import GameRuleError, TurnManager


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


if __name__ == "__main__":
    unittest.main()
