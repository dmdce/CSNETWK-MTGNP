import logging
import struct
import sys
import socket
import json
import time
import threading
import argparse
from protocol import MAX_PDU_SIZE
from console_logger import setup_logging, get_logger

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
        self.host = HOST
        self.port = PORT
        self.sock = None
        self.seq_num = 0
        self.last_ping_seq = -1
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

                logging.debug(f"[PING] Sending heartbeat (seq: {self.seq_num}). Waiting for PONG...")
                self._send_pdu(ping_pdu)

    def _on_pong_timeout(self):
        """
        name: _on_pong_timeout
        description: Called when the PONG response times out, forcing the socket to close to trigger reconnection.
        """

        logging.error(f"[client] TIMEOUT: No PONG received for seq {self.last_ping_seq} within 10s.")
        logging.debug("[client] Closing connection due to no response from server...")

        if self.sock:
            try:
                # Force close to trigger reconnection
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except:
                pass

    def _start_input_thread(self):
        """
        name: _start_input_thread
        description: Spawns a background daemon thread to capture CLI input from stdin continuously.
        """
        input_thread = threading.Thread(target=self._input_loop, daemon=True)
        input_thread.start()

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

        # --- MULLIGAN PHASE ---
        if self.current_phase == "MULLIGAN":
            if cmd in ["mulligan", "mull", "m"]:
                self.mulligan_count += 1
                pdu = {
                    "type": "MULLIGAN_CHOICE",
                    "seq_num": self.last_server_seq,
                    "keep": False,
                    "cards_to_bottom": []
                }
                print(f"[ACTION] Requesting mulligan #{self.mulligan_count}...")
                self._send_pdu(pdu)

            elif cmd in ["keep", "k"]:
                provided_cards = tokens[1:]

                # Validate bottom card count
                if len(provided_cards) != self.mulligan_count:
                    print(f"❌ Error: You mulliganed {self.mulligan_count} time(s). You must supply exactly {self.mulligan_count} card ID(s) to bottom.")
                    print(f"   Usage example: keep {' '.join(self.current_hand[:self.mulligan_count])}")
                    return

                # Validate selected cards are present in current hand
                temp_hand = list(self.current_hand)
                for card_id in provided_cards:
                    if card_id not in temp_hand:
                        print(f"❌ Error: Card '{card_id}' is not in your current hand.")
                        return
                    temp_hand.remove(card_id)

                pdu = {
                    "type": "MULLIGAN_CHOICE",
                    "seq_num": self.last_server_seq,
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

        else:
            print(f"Command '{cmd}' not recognized for current phase: {self.current_phase}")

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

        # Track incoming server sequence numbers to echo back in Mulligan choices
        if "seq_num" in pdu:
            self.last_server_seq = pdu["seq_num"]

        if p_type == "PONG":
            if pdu.get("seq_num") == self.last_ping_seq:
                if self.pong_timer:
                    self.pong_timer.cancel()

                latency = round((time.time() - pdu.get("timestamp")) * 1000, 2)
                logging.debug(f"[PONG] Received. Latency: {latency}ms, ping timer cancelled")
            else:
                logger.warning(f"??? Received stale PONG (expected {self.last_ping_seq}, got {pdu.get('seq_num')})")

        elif p_type == "GAME_STATE_UPDATE":
            state = pdu.get("state", {})
            self.current_phase = state.get("phase")
            self.current_hand = state.get("hand", [])

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
                    print(f"Enter command: 'discard <card_id1> ...' ({self.mulligan_count} card(s) to bottom) OR 'mulligan'")
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

            # logging.debug(f"Received GAME_STATE_UPDATE: {pdu}")
            logger.debug(
                "Received GAME_STATE_UPDATE:\n%s",
                json.dumps(pdu, indent=2, sort_keys=True),
            )

        elif p_type == "ERROR":
            logging.error(f"ERROR from server ({pdu.get('code')}): {pdu.get('message')}")

        elif p_type == "GAME_OVER":
            print(f"\n--- GAME OVER ---")
            print(f"Winner: {pdu.get('winner_id')} | Loser: {pdu.get('loser_id')}")
            print(f"Reason: {pdu.get('reason')}")

            print(f"You are returning to the lobby. Wait for your next game.")
            self.seq_num = 0
            self.mulligan_count = 0

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