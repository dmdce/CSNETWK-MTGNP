import struct
import sys
import socket
import json
import time
import threading
from protocol import MAX_PDU_SIZE

HOST = socket.gethostbyname(socket.gethostname())
PORT = 4444
VERBOSE_MODE = False

class MTGNPClient:
    def __init__(self, player_id):
        self.player_id = player_id
        self.host = HOST
        self.port = PORT
        self.sock = None
        self.seq_num = 0
        self.last_ping_seq = -1
        self.pong_timer = None
        self.is_running = True
        self.deck = ["mountain_001", "shock_001", "goblin_guide_001"] # Temporary

    def _start_heartbeat(self):
        thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        thread.start()

    def _heartbeat_loop(self):
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

                if VERBOSE_MODE: print(f"[PING] Sending heartbeat (seq: {self.seq_num}). Waiting for PONG...")
                self._send_pdu(ping_pdu)

    def _on_pong_timeout(self):
        if VERBOSE_MODE:
            print(f"[client] TIMEOUT: No PONG received for seq {self.last_ping_seq} within 10s.")
            print("[client] Closing connection due to no response from server...")

        if self.sock:
            try:
                # Force close to trigger reconnection
                self.sock.shutdown(socket.SHUT_RDWR)
                self.sock.close()
            except:
                pass

    def _send_pdu(self, pdu):
        try:
            payload = json.dumps(pdu).encode('utf-8')

            if len(payload) > MAX_PDU_SIZE:
                if VERBOSE_MODE: print(f"[client] Failed to send PDU: payload of {len(payload)} bytes exceeds max PDU size of {MAX_PDU_SIZE}")
                return

            header = struct.pack('>I', len(payload))
            self.sock.sendall(header + payload)
        except (socket.error, AttributeError):
            if VERBOSE_MODE: print("[client] Failed to send PDU: Socket not connected.")

    def _recv_exact(self, num_bytes):
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
        try:
            header = self._recv_exact(4)
            if header is None:
                return None

            length = struct.unpack('>I', header)[0]

            if length > MAX_PDU_SIZE:
                if VERBOSE_MODE: print(f"[client] Rejecting incoming PDU: declared length {length} bytes exceeds max size of {MAX_PDU_SIZE}")
                return None

            body = self._recv_exact(length)
            if body is None:
                return None

            return json.loads(body.decode('utf-8'))
        except (socket.error, struct.error, json.JSONDecodeError, UnicodeDecodeError):
            return None

    def connect_and_identify(self):
        while self.is_running:
            try:
                if VERBOSE_MODE: print(f"[client] Attempting to connect to {self.host}:{self.port}...")
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

                # Bound connection attempt
                self.sock.settimeout(15.0)
                self.sock.connect((self.host, self.port))
                # Let PING/PONG detect the dead link once connection is established
                self.sock.settimeout(None)

                if VERBOSE_MODE: print(f"[client] Connected. Sending PLAYER_READY for '{self.player_id}'...")
                self.seq_num += 1
                ready_pdu = {
                    "type": "PLAYER_READY",
                    "seq_num": self.seq_num,
                    "player_id": self.player_id,
                    "deck_list": self.deck
                }
                if VERBOSE_MODE: print(f"[client] Sending PDU to server: {ready_pdu}")
                self._send_pdu(ready_pdu)
                return True

            except (socket.error, ConnectionRefusedError):
                if VERBOSE_MODE: print("[client] Connection failed. Retrying in 5 seconds...")
                time.sleep(5)
        return False

    def run(self):
        if not self.connect_and_identify():
            return

        self._start_heartbeat()

        while self.is_running:
            pdu = self._recv_pdu()

            if pdu is None:
                if VERBOSE_MODE: print("\n[client] !!! TCP Disconnect detected by Peer!")
                # Try to reconnect immediately
                if self.connect_and_identify():
                    continue
                else:
                    break

            self.handle_pdu(pdu)

    def handle_pdu(self, pdu):
        p_type = pdu.get("type")

        if p_type == "PONG":
            # timestamp = pdu.get("timestamp")
            # seqnum = pdu.get("seq_num")
            # latency = round((time.time() - timestamp) * 1000, 2)
            # print(f"[PONG] Heartbeat acknowledged. (seq: {seqnum}, latency: {latency} ms)")
            if pdu.get("seq_num") == self.last_ping_seq:
                if self.pong_timer:
                    self.pong_timer.cancel()

                latency = round((time.time() - pdu.get("timestamp")) * 1000, 2)
                if VERBOSE_MODE: print(f"[PONG] Received. Latency: {latency}ms, ping timer cancelled")
            else:
                if VERBOSE_MODE: print(f"[client] ??? Received stale PONG (expected {self.last_ping_seq}, got {pdu.get('seq_num')})")

        elif p_type == "GAME_STATE_UPDATE":
            state = pdu.get("state", {})
            print(f"\n--- STATE UPDATE (Seq: {pdu.get('seq_num')}) ---")
            print(f"Phase: {state.get('phase')}")
            print(f"Players Ready: {state.get('players_ready')}")
            if state.get('waiting_for'):
                print(f"Waiting for: {state.get('waiting_for')}")

            if VERBOSE_MODE: print(f"[client] Received GAME_STATE_UPDATE: {pdu}")

        elif p_type == "ERROR":
            if VERBOSE_MODE: print(f"\n[client] ERROR from server ({pdu.get('code')}): {pdu.get('message')}")

        elif p_type == "GAME_OVER":
            print(f"\n--- GAME OVER ---")
            print(f"Winner: {pdu.get('winner_id')} | Loser: {pdu.get('loser_id')}")
            print(f"Reason: {pdu.get('reason')}")

            if VERBOSE_MODE: print("[client] Returning to lobby. Waiting for next game.")
            self.seq_num = 0

        elif p_type == "PING":
            self._send_pdu({"type": "PONG", "seq_num": pdu.get("seq_num")})

if __name__ == '__main__':
    if len(sys.argv) > 1:
        player = sys.argv[1]
        if "verbose" in sys.argv[1:]: VERBOSE_MODE = True
    else:
        player = "anonymous"

    client = MTGNPClient(player_id = player)
    if VERBOSE_MODE:
        print("[client] Verbose mode active!\n")
    else:
        print("NOTE: Verbose mode is not active. Debug lines are hidden. Include 'verbose' as a flag to activate verbose mode.\n")

    try:
        client.run()
    except KeyboardInterrupt:
        if VERBOSE_MODE: print("\n[client] Detected force stop. Exiting...")
        client.is_running = False