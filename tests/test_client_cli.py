import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from client import MTGNPClient
from engine import GameEngine
from turn_manager import TurnManager


class ClientPriorityCliTests(unittest.TestCase):
    def setUp(self):
        self.client = MTGNPClient("p1")
        self.sent = []
        self.client._send_pdu = self.sent.append
        self.client.current_phase = "UPKEEP"

    def test_priority_grant_enables_cli_pass(self):
        self.client.handle_pdu({
            "type": "PRIORITY_GRANT",
            "player_id": "p1",
            "seq_num": 42,
            "time_limit_ms": 60000,
        })
        self.client._handle_user_command("pass")
        self.assertEqual([{"type": "PRIORITY_PASS", "seq_num": 42}], self.sent)
        self.assertFalse(self.client.has_priority)

    def test_client_cannot_pass_without_priority(self):
        self.client._handle_user_command("pass")
        self.assertEqual([], self.sent)

    def test_phase_transition_updates_cli_phase(self):
        self.client.handle_pdu({
            "type": "PHASE_TRANSITION",
            "seq_num": 43,
            "from_phase": "UPKEEP",
            "to_phase": "DRAW",
            "active_player": "p1",
            "turn": 1,
        })
        self.assertEqual("DRAW", self.client.current_phase)


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


class PhaseProgressionTests(unittest.TestCase):
    def test_two_cli_passes_advance_upkeep_to_draw(self):
        server = FakeServer()
        engine = GameEngine(server)
        engine.player_ids = ["p1", "p2"]
        engine.state = {
            "turn": 1,
            "phase": "UPKEEP",
            "active_player": "p1",
            "priority_holder": None,
            "life_totals": {"p1": 20, "p2": 20},
            "hand": {"p1": [], "p2": []},
            "hand_counts": {"p1": 0, "p2": 0},
            "libraries": {"p1": ["card_001"], "p2": ["card_002"]},
            "battlefield": {"p1": [], "p2": []},
            "graveyard": {"p1": [], "p2": []},
            "stack": [],
            "land_played_this_turn": False,
        }
        engine.turn_manager = TurnManager(engine.state, engine.player_ids)

        engine.grant_priority("p1")
        engine.handle_priority_pass("p1", {"type": "PRIORITY_PASS", "seq_num": 1})
        engine.handle_priority_pass("p2", {"type": "PRIORITY_PASS", "seq_num": 2})

        self.assertEqual("DRAW", engine.state["phase"])
        self.assertTrue(any(
            pdu.get("type") == "PHASE_TRANSITION"
            and pdu.get("from_phase") == "UPKEEP"
            and pdu.get("to_phase") == "DRAW"
            for pdu in server.broadcasts
        ))
        self.assertEqual([], server.errors)

    def test_begin_combat_passes_transition_to_declare_attackers(self):
        server = FakeServer()
        engine = GameEngine(server)
        engine.player_ids = ["p1", "p2"]
        engine.state = {
            "turn": 2,
            "phase": "BEGIN_COMBAT",
            "active_player": "p1",
            "priority_holder": None,
            "life_totals": {"p1": 20, "p2": 20},
            "hand": {"p1": [], "p2": []},
            "hand_counts": {"p1": 0, "p2": 0},
            "libraries": {"p1": [], "p2": []},
            "battlefield": {"p1": [], "p2": []},
            "graveyard": {"p1": [], "p2": []},
            "stack": [],
            "land_played_this_turn": False,
        }
        engine.turn_manager = TurnManager(engine.state, engine.player_ids)

        engine.grant_priority("p1")
        engine.handle_priority_pass("p1", {"type": "PRIORITY_PASS", "seq_num": 1})
        engine.handle_priority_pass("p2", {"type": "PRIORITY_PASS", "seq_num": 2})

        self.assertEqual("DECLARE_ATTACKERS", engine.state["phase"])
        self.assertTrue(any(
            pdu.get("type") == "PHASE_TRANSITION"
            and pdu.get("from_phase") == "BEGIN_COMBAT"
            and pdu.get("to_phase") == "DECLARE_ATTACKERS"
            for pdu in server.broadcasts
        ))
        self.assertEqual([], server.errors)


if __name__ == "__main__":
    unittest.main()
