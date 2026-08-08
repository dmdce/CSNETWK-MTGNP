import logging
import os
import re
import struct
import sys
import socket
import json
import time
import threading
import argparse
from protocol import MAX_PDU_SIZE
from console_logger import setup_logging, get_logger

try:
    import openpyxl
except ImportError:
    openpyxl = None

HOST = socket.gethostbyname(socket.gethostname())
PORT = 4444

class MTGNPClient:
    def __init__(self, player_id):
        """
        name: __init__
        description: Initializes the MTGNP client with the given player ID and sets up default attributes.
        @param: player_id (str): Unique identifier for this client player.
        """

        self.player_id = player_id
        self.opponent_id = None
        self.host = HOST
        self.port = PORT
        self.sock = None
        self.seq_num = 0
        self.last_ping_seq = -1
        self.server_seq_num = None
        self.priority_seq_num = None
        self.has_priority = False
        self.last_phase_transition_seq = 0
        self.last_server_seq = 0         # Sequence number received from server's latest state update
        self.mulligan_count = 0          # Number of mulligans taken in current game
        self.current_hand = []           # Local tracking of drawn hand
        self.current_phase = "LOBBY"     # Game phase state
        self.pong_timer = None
        self.is_running = True
        self.deck = ["counterspell_001", "counterspell_002", "counterspell_003", "counterspell_004",
                    "goblin_guide_001", "goblin_guide_002", "goblin_guide_003", "goblin_guide_004",
                    "island_001", "island_002", "island_003", "island_004", "island_005", "island_006", "island_007", "island_008", "island_009", "island_010",
                    "lightning_bolt_001", "lightning_bolt_002", "lightning_bolt_003", "lightning_bolt_004",
                    "mana_leak_001", "mana_leak_002", "mana_leak_003", "mana_leak_004",
                    "monastery_swiftspear_001", "monastery_swiftspear_002", "monastery_swiftspear_003", "monastery_swiftspear_004",
                    "mountain_001", "mountain_002", "mountain_003", "mountain_004", "mountain_005", "mountain_006", "mountain_007", "mountain_008", "mountain_009", "mountain_010",
                    "phantasmal_bear_001", "phantasmal_bear_002", "phantasmal_bear_003", "phantasmal_bear_004",
                    "ponder_001", "ponder_002", "ponder_003", "ponder_004",
                    "prodigal_sorcerer_001", "prodigal_sorcerer_002"] # Temporary
        self.card_db = {}
        self._load_card_database()

    def _start_heartbeat(self):
        """
        name: _start_heartbeat
        description: Launches a background thread that periodically sends PING PDUs to the server.
        """

        thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        thread.start()

    def _heartbeat_loop(self):
        """
        name: _heartbeat_loop
        description: Continuously sends PING PDUs every 30 seconds and starts a timeout timer for each PONG.
        """

        while self.is_running:
            time.sleep(30)
            if self.sock:
                self.seq_num += 1
                self.last_ping_seq = self.seq_num

                ping_pdu = {
                    "type": "PING",
                    "seq_num": self.seq_num,
                    "timestamp": time.time()
                }

                self.pong_timer = threading.Timer(10.0, self._on_pong_timeout)
                self.pong_timer.start()

                logger.debug(f"[PING] Sending heartbeat (seq: {self.seq_num}). Waiting for PONG...")
                self._send_pdu(ping_pdu)

    def _on_pong_timeout(self):
        """
        name: _on_pong_timeout
        description: Called when the PONG response times out, forcing the socket to close to trigger reconnection.
        """

        logger.error(f"[client] TIMEOUT: No PONG received for seq {self.last_ping_seq} within 10s.")
        logger.debug("[client] Closing connection due to no response from server...")

        if self.sock:
            try:
                # Force close to trigger reconnection
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except OSError:
                pass

    def _start_input_thread(self):
        """
        name: _start_input_thread
        description: Spawns a background daemon thread to capture CLI input from stdin continuously.
        """
        input_thread = threading.Thread(target=self._input_loop, daemon=True)
        input_thread.start()

    def _load_card_database(self):
        """
        name: _load_card_database
        description: Loads card metadata from the local Excel workbook into a lookup dictionary.
        """
        if openpyxl is None:
            logger.warning("Card database support disabled because openpyxl is not installed.")
            return

        workbook_path = os.path.join(os.path.dirname(__file__), "mtgnp_master_card_list.xlsx")
        if not os.path.exists(workbook_path):
            logger.warning(f"Card database file not found: {workbook_path}")
            return

        try:
            wb = openpyxl.load_workbook(workbook_path, read_only=True, data_only=True)
            ws = wb.active

            for row in ws.iter_rows(min_row=3, values_only=True):
                if not row or row[0] is None:
                    continue

                card_data = {
                    "card_id_base": str(row[0]).strip(),
                    "card_name": str(row[1]).strip() if row[1] is not None else "",
                    "card_type": str(row[2]).strip() if row[2] is not None else "",
                    "subtype": str(row[3]).strip() if row[3] is not None else "",
                    "color": str(row[4]).strip() if row[4] is not None else "",
                    "cmc": row[5],
                    "w": row[6],
                    "u": row[7],
                    "b": row[8],
                    "r": row[9],
                    "g": row[10],
                    "generic": row[11],
                    "power": row[12],
                    "toughness": row[13],
                    "simplified_effect": str(row[15]).strip() if row[15] is not None else "",
                }

                self.card_db[card_data["card_id_base"]] = card_data
        except Exception as exc:
            logger.warning(f"Failed to load card database: {exc}")

    def _normalize_card_id(self, card_id):
        normalized = card_id.lower().strip()
        if normalized in self.card_db:
            return normalized
        stripped = re.sub(r'_[0-9]+$', '', normalized)
        return stripped if stripped in self.card_db else normalized

    def _get_card_info(self, card_id):
        normalized_id = self._normalize_card_id(card_id)
        return self.card_db.get(normalized_id)

    def _format_card_value(self, value):
        if value is None:
            return "-"
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)

    def _print_card_info(self, card_data):
        print(f"\n--- CARD INFO: {card_data['card_name']} ({card_data['card_id_base']}) ---")
        print(f"Card ID Base: {card_data['card_id_base']}")
        print(f"Name: {card_data['card_name']}")
        print(f"Type: {card_data['card_type']}")
        if card_data.get("subtype"):
            print(f"Subtype: {card_data['subtype']}")
        print(f"Color: {card_data['color']}")
        print(f"CMC: {self._format_card_value(card_data['cmc'])}")
        print(
            "Mana: "
            f"W={self._format_card_value(card_data['w'])} "
            f"U={self._format_card_value(card_data['u'])} "
            f"B={self._format_card_value(card_data['b'])} "
            f"R={self._format_card_value(card_data['r'])} "
            f"G={self._format_card_value(card_data['g'])} "
            f"Generic={self._format_card_value(card_data['generic'])}"
        )
        print(f"Power/Toughness: {self._format_card_value(card_data['power'])}/{self._format_card_value(card_data['toughness'])}")
        print(f"Effect: {card_data['simplified_effect']}")

    def _handle_view_command(self, card_id):
        card_info = self._get_card_info(card_id)
        if card_info is None:
            print(f"Card '{card_id}' not found in the card database.")
            return
        self._print_card_info(card_info)

    def _input_loop(self):
        """
        name: _input_loop
        description: Reads standard input line-by-line in a loop and passes lines to command handlers.
        """
        while self.is_running:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd_str = line.strip()
                if cmd_str:
                    self._handle_user_command(cmd_str)
            except Exception as e:
                logger.error(f"Input thread error: {e}")
                break

    def _handle_user_command(self, cmd_str):
        """
        name: _handle_user_command
        description: Parses CLI commands typed by the player according to current game phase rules.
        @param: cmd_str (str): Raw string command typed in standard input.
        """
        tokens = cmd_str.strip().split()
        cmd = tokens[0].lower() if tokens else ""

        if cmd == "view":
            if len(tokens) < 2:
                print("Usage: view <card_id>")
                return
            self._handle_view_command(tokens[1])
            return

        # --- MULLIGAN PHASE ---
        if self.current_phase == "MULLIGAN":
            if cmd in ["mulligan", "mull", "m"]:
                self.mulligan_count += 1
                pdu = {
                    "type": "MULLIGAN_CHOICE",
                    "seq_num": self.server_seq_num,
                    "keep": False,
                    "cards_to_bottom": []
                }
                print(f"[ACTION] Requesting mulligan #{self.mulligan_count}...")
                self._send_pdu(pdu)

            elif cmd in ["keep", "k"]:
                provided_cards = tokens[1:]

                # Validate bottom card count
                if len(provided_cards) != self.mulligan_count:
                    print(f"Error: You mulliganed {self.mulligan_count} time(s). You must supply exactly {self.mulligan_count} card ID(s) to bottom.")
                    print(f"   Usage example: keep {' '.join(self.current_hand[:self.mulligan_count])}")
                    return

                # Validate selected cards are present in current hand
                temp_hand = list(self.current_hand)
                for card_id in provided_cards:
                    if card_id not in temp_hand:
                        print(f"Error: Card '{card_id}' is not in your current hand.")
                        return
                    temp_hand.remove(card_id)

                pdu = {
                    "type": "MULLIGAN_CHOICE",
                    "seq_num": self.server_seq_num,
                    "keep": True,
                    "cards_to_bottom": provided_cards
                }
                print(f"[ACTION] Keeping hand. Cards sent to bottom: {provided_cards}")
                self._send_pdu(pdu)

            elif cmd == "help":
                print("\n--- MULLIGAN COMMANDS ---")
                print("  keep <card_ids...> / k <card_ids...> : Keep current hand (specify card IDs to bottom)")
                print("  mulligan / m                          : Redraw a new hand\n")

            else:
                print(f"Unknown command for Mulligan Phase. Type 'keep' or 'mulligan'.")

        # --- LOBBY PHASE ---
        elif self.current_phase == "LOBBY":
            if cmd == "ready":
                self.seq_num += 1
                ready_pdu = {
                    "type": "PLAYER_READY",
                    "seq_num": self.seq_num,
                    "player_id": self.player_id,
                    "deck_list": self.deck
                }
                print("[ACTION] Re-sending PLAYER_READY...")
                self._send_pdu(ready_pdu)
            elif cmd == "help":
                print("\n--- LOBBY COMMANDS ---")
                print("  ready : Re-send player readiness to server\n")
            else:
                print("In lobby. Waiting for match setup... (type 'ready' to re-send readiness)")

        # --- IN-GAME PHASES ---
        else:
            if cmd in ("pass", "p"):
                if not self.has_priority or self.priority_seq_num is None:
                    print("Error: You cannot pass because you do not currently hold priority.")
                    return
                self._send_pdu({
                    "type": "PRIORITY_PASS",
                    "seq_num": self.priority_seq_num,
                })
                self.has_priority = False
                print("[ACTION] Priority passed.")

            elif cmd in ("cast", "c"):
                if len(tokens) < 2:
                    print("Usage: cast <card_id> [target1 target2...]")
                    return
                card_id = tokens[1]
                targets = tokens[2:] if len(tokens) > 2 else []
                pdu = {
                    "type": "CAST_SPELL",
                    "seq_num": self.priority_seq_num,
                    "card_id": card_id,
                    "targets": targets,
                    "mana_payment": {}
                }
                print(f"[ACTION] Casting spell '{card_id}' with targets: {targets}")
                self._send_pdu(pdu)

            elif cmd in ("land", "l"):
                if len(tokens) < 2:
                    print("Usage: land <card_id>")
                    return
                card_id = tokens[1]
                pdu = {
                    "type": "PLAY_LAND",
                    "seq_num": self.priority_seq_num,
                    "card_id": card_id
                }
                print(f"[ACTION] Playing land '{card_id}'")
                self._send_pdu(pdu)

            elif cmd in ("activate", "act"):
                if len(tokens) < 3:
                    print("Usage: activate <source_id> <ability_index> [target1...]")
                    return
                source_id = tokens[1]
                try:
                    ability_idx = int(tokens[2])
                except ValueError:
                    print("Error: <ability_index> must be an integer (e.g., 0, 1).")
                    return
                targets = tokens[3:] if len(tokens) > 3 else []
                pdu = {
                    "type": "ACTIVATE_ABILITY",
                    "seq_num": self.priority_seq_num,
                    "source_id": source_id,
                    "ability_index": ability_idx,
                    "targets": targets,
                    "cost_payment": {}
                }
                print(f"[ACTION] Activating ability index {ability_idx} on '{source_id}' targeting {targets}")
                self._send_pdu(pdu)

            elif cmd in ("attack", "att", "a"):
                if len(tokens) < 2:
                    print("Usage: attack <creature_id1> [creature_id2...]")
                    return
                attackers = [{"creature_id": cid, "target": self.opponent_id} for cid in tokens[1:]]
                pdu = {
                    "type": "DECLARE_ATTACKERS",
                    "seq_num": self.last_phase_transition_seq,
                    "attackers": attackers
                }
                print(f"[ACTION] Declaring attackers: {[a['creature_id'] for a in attackers]}")
                self._send_pdu(pdu)

            elif cmd in ("block", "b"):
                if len(tokens) < 3:
                    print("Usage: block <blocker_creature_id> <attacking_creature_id>")
                    return
                blocker_id = tokens[1]
                attacker_id = tokens[2]
                pdu = {
                    "type": "DECLARE_BLOCKERS",
                    "seq_num": self.last_phase_transition_seq,
                    "blockers": [{
                        "creature_id": blocker_id,
                        "blocking_id": attacker_id
                    }]
                }
                print(f"[ACTION] Declaring blocker '{blocker_id}' -> blocking '{attacker_id}'")
                self._send_pdu(pdu)

            elif cmd == "order_damage":
                if len(tokens) < 3:
                    print("Usage: order_damage <attacker_id> <blocker1_id> <blocker2_id>...")
                    return
                attacker_id = tokens[1]
                ordered_blockers = tokens[2:]
                pdu = {
                    "type": "ASSIGN_DAMAGE_ORDER",
                    "seq_num": self.last_phase_transition_seq,
                    "attacker_id": attacker_id,
                    "ordered_blocker_ids": ordered_blockers
                }
                print(f"[ACTION] Ordering combat damage for '{attacker_id}': {ordered_blockers}")
                self._send_pdu(pdu)

            elif cmd == "discard":
                if len(tokens) < 2:
                    print("Usage: discard <card_id1> [card_id2...]")
                    return
                cards_to_discard = tokens[1:]
                pdu = {
                    "type": "DISCARD",
                    "seq_num": self.server_seq_num,
                    "cards": cards_to_discard
                }
                print(f"[ACTION] Discarding cards: {cards_to_discard}")
                self._send_pdu(pdu)

            elif cmd == "concede":
                self._send_pdu({
                    "type": "CONCEDE",
                    "seq_num": self.server_seq_num,
                    "player_id": self.player_id,
                })
                self.has_priority = False
                print("[ACTION] Conceding the game...")

            elif cmd == "help":
                print("\n--- IN-GAME COMMANDS ---")
                print("  pass / p                              : Pass priority")
                print("  land <card_id> / l <card_id>          : Play a land")
                print("  cast <card_id> [targets...]           : Cast a spell")
                print("  activate <src> <idx> [targets...]     : Activate permanent ability")
                print("  attack <creature_ids...>              : Declare attacking creatures")
                print("  block <blocker_id> <attacker_id>      : Declare blocking creature")
                print("  order_damage <attacker> <blockers...> : Assign damage order to blockers")
                print("  discard <card_ids...>                 : Discard cards during Cleanup")
                print("  concede                               : Concede the current game\n")

            else:
                print(f"Command '{cmd}' not recognized for current phase: {self.current_phase}. Type 'help'.")

    def _send_pdu(self, pdu):
        """
        name: _send_pdu
        description: Serializes a PDU to JSON, frames it with a length prefix, and sends it over the socket.
        @param: pdu (dict): The PDU object to send.
        """

        try:
            payload = json.dumps(pdu).encode('utf-8')

            if len(payload) > MAX_PDU_SIZE:
                logger.error(f"Failed to send PDU: payload of {len(payload)} bytes exceeds max PDU size of {MAX_PDU_SIZE}")
                return

            header = struct.pack('>I', len(payload))
            self.sock.sendall(header + payload)
        except (socket.error, AttributeError):
            logger.error(f"Failed to send PDU: Socket not connected.")

    def _recv_exact(self, num_bytes):
        """
        name: _recv_exact
        description: Reads exactly num_bytes from the socket, returning the data as bytes.
        @param: num_bytes (int): Number of bytes to read.
        @return: bytes: The received data, or None if connection closed.
        """

        chunks = []
        bytes_received = 0

        while bytes_received < num_bytes:
            chunk = self.sock.recv(min(num_bytes - bytes_received, 4096))
            if not chunk:
                return None
            chunks.append(chunk)
            bytes_received += len(chunk)

        return b"".join(chunks)

    def _recv_pdu(self):
        """
        name: _recv_pdu
        description: Reads a framed PDU from the socket, parses it as JSON, and returns the decoded dictionary.
        @return: dict or None: The parsed PDU, or None on error or disconnect.
        """

        try:
            header = self._recv_exact(4)
            if header is None:
                return None

            length = struct.unpack('>I', header)[0]

            if length > MAX_PDU_SIZE:
                logger.error(f"Rejecting incoming PDU: declared length {length} bytes exceeds max size of {MAX_PDU_SIZE}")
                return None

            body = self._recv_exact(length)
            if body is None:
                return None

            return json.loads(body.decode('utf-8'))
        except (socket.error, struct.error, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def connect_and_identify(self):
        """
        name: connect_and_identify
        description: Establishes a TCP connection to the server and sends a PLAYER_READY PDU with the player's deck.
        @return: bool: True if connection and identification succeeded, False otherwise.
        """

        while self.is_running:
            try:
                logger.debug(f"Attempting to connect to {self.host}:{self.port}...")
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

                # Bound connection attempt
                self.sock.settimeout(15.0)
                self.sock.connect((self.host, self.port))
                # Let PING/PONG detect the dead link once connection is established
                self.sock.settimeout(None)

                logger.debug(f"Connected. Sending PLAYER_READY for '{self.player_id}'...")
                self.seq_num += 1
                self.mulligan_count = 0

                ready_pdu = {
                    "type": "PLAYER_READY",
                    "seq_num": self.seq_num,
                    "player_id": self.player_id,
                    "deck_list": self.deck
                }
                logger.debug(f"Sending PDU to server: {ready_pdu}")
                self._send_pdu(ready_pdu)
                return True

            except (socket.error, ConnectionRefusedError):
                logger.error(f"Connection failed. Retrying in 5 seconds...")
                time.sleep(5)
        return False

    def run(self):
        """
        name: run
        description: Main client loop that connects, starts heartbeat, input reader thread, and processes incoming PDUs.
        """

        if not self.connect_and_identify():
            return

        self._start_heartbeat()
        self._start_input_thread()

        while self.is_running:
            pdu = self._recv_pdu()

            if pdu is None:
                logger.error("!!! TCP Disconnect detected by Peer!")
                # Try to reconnect immediately
                if self.connect_and_identify():
                    continue
                else:
                    break

            self.handle_pdu(pdu)

    def handle_pdu(self, pdu):
        """
        name: handle_pdu
        description: Dispatches incoming PDUs to appropriate handling logic based on the message type.
        @param: pdu (dict): The received PDU dictionary.
        """

        p_type = pdu.get("type")

        # Capture seq_num from server PDU (GAME_STATE_UPDATE, PRIORITY_GRANT, ...)
        if p_type in ("GAME_STATE_UPDATE", "PRIORITY_GRANT", "PHASE_TRANSITION"):
            self.server_seq_num = pdu.get("seq_num")

        # Track incoming server sequence numbers to echo back in Mulligan choices
        if "seq_num" in pdu:
            self.last_server_seq = pdu["seq_num"]

        if p_type == "PONG":
            if pdu.get("seq_num") == self.last_ping_seq:
                if self.pong_timer:
                    self.pong_timer.cancel()

                latency = round((time.time() - pdu.get("timestamp")) * 1000, 2)
                logger.debug(f"[PONG] Received. Latency: {latency}ms, ping timer cancelled")
            else:
                logger.warning(f"??? Received stale PONG (expected {self.last_ping_seq}, got {pdu.get('seq_num')})")

        elif p_type == "GAME_STATE_UPDATE":
            state = pdu.get("state", {})
            self.current_phase = state.get("phase")
            self.current_hand = state.get("hand", [])

            # Ensure priority holder matches server state exactly
            priority_holder = state.get("priority_holder")
            if priority_holder is not None:
                self.has_priority = (priority_holder == self.player_id)

            life_totals = state.get("life_totals", {})
            for pid in life_totals.keys():
                if pid != self.player_id:
                    self.opponent_id = pid

            print(f"\n--- STATE UPDATE (Seq: {self.last_server_seq}) ---")
            print(f"Phase: {self.current_phase}")

            if self.current_phase == "LOBBY":
                print(f"Players Ready: {state.get('players_ready', 0)}")
                if state.get('waiting_for'):
                    print(f"Waiting for: {state.get('waiting_for')}")

            elif self.current_phase == "MULLIGAN":
                print(f"================ MULLIGAN PHASE ================")
                print(f"Your Hand ({len(self.current_hand)} cards): {self.current_hand}")
                print(f"Times Mulliganed: {self.mulligan_count}")
                if self.mulligan_count > 0:
                    print(f"Enter command: 'keep <card_id1> ...' ({self.mulligan_count} card(s) to bottom) OR 'mulligan'")
                else:
                    print(f"Enter command: 'keep' OR 'mulligan'")
                print(f"================================================")

            else:
                print(f"Turn: {state.get('turn')} | Active Player: {state.get('active_player')}")
                print(f"Life Totals: {state.get('life_totals', {})}")
                print(f"Your Hand: {self.current_hand}")
                print(f"Opponent Hand Count: {state.get('hand_counts', {})}")
                print(f"Library Counts: {state.get('library_counts', {})}")
                print(f"Battlefield: {state.get('battlefield', {})}")
                print(f"Graveyard: {state.get('graveyard', {})}")
                print(f"Stack: {state.get('stack', [])}")

            logger.debug(
                "Received GAME_STATE_UPDATE:\n%s",
                json.dumps(pdu, indent=2, sort_keys=True),
            )

        elif p_type == "PHASE_TRANSITION":
            to_phase = pdu.get("to_phase")
            self.current_phase = pdu.get("to_phase", self.current_phase)
            self.last_phase_transition_seq = pdu.get("seq_num", self.last_phase_transition_seq)
            self.has_priority = False

            # Only print special notices to avoid duplicating GAME_STATE_UPDATE output
            if to_phase == "END_OF_COMBAT":
                print("\n[PHASE] Entering End of Combat Step. Priority window open.")
            elif to_phase == "POSTCOMBAT_MAIN":
                print("\n[PHASE] Combat concluded. Advanced to Postcombat Main Phase.")

        elif p_type == "PRIORITY_GRANT":
            if pdu.get("player_id") == self.player_id:
                self.priority_seq_num = pdu.get("seq_num")
                self.has_priority = True
                print(f"\n[PRIORITY] You have priority (seq {self.priority_seq_num}).")
                print("Type 'pass' to pass priority, or 'help' for available commands.")

        elif p_type == "COMBAT_DAMAGE_RESULT":
            print(f"\n================ COMBAT DAMAGE RESOLVED ================")
            damage_events = pdu.get("damage_events", [])

            if damage_events:
                for event in damage_events:
                    print(f"{event.get('source')} dealt {event.get('amount')} damage to {event.get('target')}.")
            else:
                print("No combat damage was dealt.")
            life_totals = pdu.get("life_totals", {})

            if life_totals:
                print(f"Life Totals: {life_totals}")
            creatures_died = pdu.get("creatures_died", [])
            if creatures_died:
                print(f"Creatures destroyed: {', '.join(creatures_died)}")

            print(f"========================================================\n")

        elif p_type == "ERROR":
            logger.error(f"ERROR from server ({pdu.get('code')}): {pdu.get('message')}")

        elif p_type == "GAME_OVER":
            print(f"\n--- GAME OVER ---")
            print(f"Winner: {pdu.get('winner_id')} | Loser: {pdu.get('loser_id')}")
            print(f"Reason: {pdu.get('reason')}")

            print(f"You are returning to the lobby. The game will find a new opponent in 10 seconds.")
            self.seq_num = 0
            self.mulligan_count = 0

            # Automatically start new game
            time.sleep(10)
            self.run()

        elif p_type == "PING":
            self._send_pdu({"type": "PONG", "seq_num": pdu.get("seq_num")})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Client application")
    parser.add_argument('--verbose', action='store_true', help="Enable verbose mode. Includes DEBUG, INFO, WARNING")
    parser.add_argument('--name', type=str, default='anonymous', help="Custom name for the client")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)
    logger = get_logger(__name__)

    if args.verbose:
        logger.info("Verbose mode active!\n")
    else:
        print("NOTE: Verbose mode is not active. Debug lines are hidden. Include '--verbose' as a flag to activate verbose mode.\n")

    client = MTGNPClient(player_id=args.name)

    try:
        client.run()
    except KeyboardInterrupt:
        logger.debug("Detected force stop. Exiting...")
        client.is_running = False
