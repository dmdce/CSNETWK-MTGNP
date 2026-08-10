# Magic: The Gathering Network Protocol (MTGNP) for CSNETWK

**MTGNP** is a TCP-based client-server implementation of a simplified, two-player *Magic: The Gathering* card game. The server acts as the sole authority for all game logic, managing turns, the stack, priority, combat, and state-based actions. Clients are thin renderers that send player actions and receive personalized game state updates.

The protocol and implementation follow the [MTGNP RFC v1.0](https://docs.google.com/document/d/1m-INIX8lu9nMxxLh-33n4gP8NxrpAJzgOSODM6hqJyQ/edit?usp=sharing).

---

## A. Build & Run Instructions

### Prerequisites
- Python 3.8 or higher (no external libraries required)
- All source files must be in the same directory (src directory inside the package):
  - `client.py`
  - `client_ui.py`
  - `console_logger.py`
  - `engine.py`
  - `logger.py`
  - `mtgnp_master_card_list.xlsx`
  - `protocol.py`
  - `server.py`
  - `server_ui.py`
  - `turn_manager.py`
  - `ui_theme.py`

### Running the Server

#### Graphical host console (recommended)

```bash
pip install -r requirements.txt
python src/server_ui.py --verbose
```

The host console provides listener configuration, player connection health, live match telemetry, lobby reset controls, and an event stream.

#### Command-line server

```bash
python src/server.py --verbose
```

| Argument |	Description |
| - | - |
| `--verbose` (optional) | Prints all sent/received PDUs and internal logs to the console. |

#### Example
> ```bash
> python src/server.py --verbose
> ```

### Running the Client

#### Graphical game client (recommended)

```bash
pip install -r requirements.txt
python src/client_ui.py --verbose
```

The graphical client uses the master card workbook for card names, mana costs, types, stats, colors, and effect text. Select cards directly on the table, inspect them in the right panel, and use the contextual action controls.

#### Command-line client

```bash
python src/client.py --verbose --name NAME
```

| Argument |	Description |
| - | - |
| `--verbose`	(optional) | Enables detailed PDU logging on the client side. |
| `--name`	(optional) | Sets the player's display ID (default: anonymous). Must be unique per lobby. |
| `NAME` | The playe's display ID. Must be specified after inserting `--name`. |

#### Example
> ```bash
> python src/client.py --name Alice --verbose
> python src/client.py --name Bob
> python src/client.py --verbose
> ```

> [!NOTE]
> Two clients must connect to the same server to start a game. The server listens on `localhost:4444` by default.

---

## B. Work Distribution Matrix

The contribution matrix disclosed will formalize the contribution of each of the members to the machine project. It is important that the members agree with the figures and remarks imparted here, and it is expected that all have arrived at the same conclusion in good faith.

| TASK / FEATURE | Aya-ay, V. | Barras, A. | Esguerra, D. | Policarpio, R. | SUM |
| --- | --- | --- | --- | --- | --- |
| **TCP Server: connection handling, framing, dispatch** | 13.0000% | 5.0000% | 77.0000% | 5.0000% | 100.0000% |
| **Game lifecycle: LOBBY, GAME_SETUP, MULLIGAN logic** | 90.0000% | 3.3333% | 3.3333% | 3.3333% | 99.9999% |
| **Turn & phase engine (all phases/steps, transitions)** | 5.0000% | 85.0000% | 5.0000% | 5.0000% | 100.0000% |
| **Priority & Stack logic, spell/ability resolution** | 5.0000% | 85.0000% | 5.0000% | 5.0000% | 100.0000% |
| **Combat system (attackers, blockers, damage)** | 5.0000% | 5.0000% | 5.0000% | 85.0000% | 100.0000% |
| **Client implementation & state rendering** | 20.0000% | 5.0000% | 5.0000% | 70.0000% | 100.0000% |
| **PDU serialisation/deserialisation (all 25 PDU types)** | 25.0000% | 25.0000% | 25.0000% | 25.0000% | 100.0000% |
| **Error handling, PING/PONG heartbeat, disconnect logic** | 40.0000% | 10.0000% | 40.0000% | 10.0000% | 100.0000% |
| **Verbose mode (client + server PDU logging, toggle on/off)** | 5.0000% | 5.0000% | 70.0000% | 20.0000% | 100.0000% |
| **Testing & interoperability** | 40.0000% | 20.0000% | 20.0000% | 20.0000% | 100.0000% |
| **README / documentation / AI disclosure** | 25.0000% | 25.0000% | 25.0000% | 25.0000% | 100.0000% |
| **AVERAGE CONTRIBUTION** | **24.8182%** | **24.8485%** | **25.4848%** | **24.8485%** | **100.0000%** |

---

## C. Deviations from the RFC

There were no limitations nor deviations from the MTGNP RFC specifications. However, additional features were made to enhance the output of the project, such as implementing card effects, a graphical interface, and viewing client-side card statistics and effects in the graphical interface and the CLI.
