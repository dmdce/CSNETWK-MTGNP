# logger.py
import json
import time

def log_pdu(pdu, direction="SENT", filename="game_stream.jsonl"):
    """Appends a single PDU line with timestamp and direction metadata."""
    log_entry = {
        "timestamp": round(time.time(), 3),
        "direction": direction,
        "pdu": pdu
    }
    with open(filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

def clear_log(filename="game_stream.jsonl"):
    """Clears the old log file when starting a new server or game run."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write("")