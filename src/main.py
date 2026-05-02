from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Static, Footer, Header, ProgressBar, Button
from textual.events import Key
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from rich.text import Text
from dataclasses import dataclass
from typing import cast
import json
import sys
import random


# === Configuration ===
TERRAIN_TILE: dict[str, str] = {
    # Solid tiles
    "WALL": "#",
    "FLOOR": ".",
    # Doors
    "CLOSED_DOOR": "+",
    "OPEN_DOOR": "/",
    # Stairs
    "DOWN_STAIRS": ">",
    # Special
    "TRAP": "?",  # Random damage
    "PORTAL": "X",  # Victory
}

ENTITY_TILE: dict[str, str] = {
    # Player
    "PLAYER": "@",
    # Monsters
    "SLIME": "S",  # A weak enemy
    "KOBOLD": "K",  # The average enemy
    "ZOMBIE": "Z",  # Lots of hp, average damage
    "MIMIC": "M",  # He is displayed as a chest, it does a lot of damage
    "BANDIT": "B",  # Give up all the money or fight
    "GHOST": "G",  # The damage goes from 2 times less
    "DEMON": "6",  # Deals high damage, but low HP
    "DRAGON": "D",  # Dungeon boss
    # NPCs
    "TRADER": "T",  # Sells armor or attack points in exchange for gold
    "WANDERER": "W",  # He can give experience for a conversation
    # Pickups
    "CHEST": "C",  # Keeps gold
    "MONEY": "$",  # Gold
    "FOOD": "%",  # Starve mechanics in future?
    "POTION": "!",  # Hit points
    "ARMOR": "=",  # Reduces incoming damage
    "WEAPON": "^",  # Increases damage
    "KEY": "~",  # Opens chests and doors
}

WALKABLE_TERRAIN: set[str] = {
    TERRAIN_TILE["FLOOR"],
    TERRAIN_TILE["OPEN_DOOR"],
    TERRAIN_TILE["DOWN_STAIRS"],
    TERRAIN_TILE["TRAP"],
    TERRAIN_TILE["PORTAL"],
}

# TODO: portal after dragon's death to escape
# TODO: Main menu with ratings (gold, kills, max stats, etc.),
# TODO: NPC and dialogs, trading window
# TODO: Traps
# TODO: Locked doors and keys


# === Map generator ===
def load_prefabs(folder: str) -> dict[str, list[list[str]]]:
    """
    Load room prefabs from `.txt` files in `folder`.
    Returns a dict mapping filenames to 2D character grids.
    """
    cache: dict[str, list[list[str]]] = {}
    for p in Path(folder).glob(pattern="*.txt"):
        with open(file=p, encoding="utf-8") as f:
            cache[p.stem] = [list(line.rstrip()) for line in f if line.strip()]
    return cache


def carve_corridor_wide(
    grid: list[list[str]], x1: int, y1: int, x2: int, y2: int, width: int = 3
):
    """
    Carve an L-shaped corridor (horizontal then vertical)
    between two points.

    Modifies `grid` in-place with the specified tile width.
    """
    h, w = len(grid), len(grid[0])
    half: int = width // 2

    # Horizontal segment
    x_start, x_end = min(x1, x2), max(x1, x2)
    for x in range(x_start, x_end + 1):
        if not (0 <= x < w):
            continue
        for dy in range(-half, half + 1):
            ny: int = y1 + dy
            if 0 <= ny < h:
                grid[ny][x] = TERRAIN_TILE["FLOOR"]

    # Vertical segment
    y_start, y_end = min(y1, y2), max(y1, y2)
    for y in range(y_start, y_end + 1):
        if not (0 <= y < h):
            continue
        for dx in range(-half, half + 1):
            nx: int = x2 + dx
            if 0 <= nx < w:
                grid[y][nx] = TERRAIN_TILE["FLOOR"]


def outside_point(room: "Room", door_x: int, door_y: int) -> tuple[int, int]:
    """
    Return the tile coordinates just outside a room at a given
    door position.
    """
    if door_x == room.x:  # left wall
        return door_x - 1, door_y
    if door_x == room.x + room.w - 1:  # right wall
        return door_x + 1, door_y
    if door_y == room.y:  # upper wall
        return door_x, door_y - 1

    return door_x, door_y + 1  # lower wall


class StatsPanel(Vertical):
    """Widget displaying HP/XP progress bars and core player stats."""

    def compose(self) -> ComposeResult:
        """Build the widget layout."""
        with Horizontal(id="bars_row"):
            yield ProgressBar(total=100, id="hp_bar", show_eta=False)
            yield ProgressBar(total=100, id="xp_bar", show_eta=False)

        with Horizontal(id="stats_text_container"):
            yield Static("", id="stats_text")

    def sync(self, stats: PlayerStats, floor: int):
        """
        Update progress bars and stats text to reflect
        current `stats` and floor.
        """

        self.query_one("#hp_bar", ProgressBar).update(
            total=stats.max_hits, progress=stats.hits
        )

        xp_target: int = stats.level * 20

        self.query_one("#xp_bar", ProgressBar).update(
            total=xp_target,
            progress=stats.xp,
        )

        # Text
        self.query_one("#stats_text", Static).update(
            Text.assemble(
                ("FLOOR:", "#1696e0"),
                (f"{floor} ", "#ffffff"),
                ("LVL:", "#16c444"),
                (f"{stats.level} ", "#ffffff"),
                ("STR:", "#e61034"),
                (f"{stats.strength} ", "#ffffff"),
                ("ARM:", "#a112c4"),
                (f"{stats.armor} ", "#ffffff"),
                ("GOLD:", "#deab14"),
                (f"{stats.gold} ", "#ffffff"),
            )
        )


@dataclass
class PlayerStats:
    """
    Dataclass tracking player attributes, inventory, and progression."""

    level: int = 1
    hits: int = 5
    max_hits: int = 20
    strength: int = 3
    armor: int = 1
    gold: int = 0
    xp: int = 0

    def take_damage(self, amount: int) -> bool:
        """
        Apply damage. Returns True if player HP reaches zero."""
        self.hits -= amount

        if self.hits <= 0:
            self.hits = 0
            # If player died:
            return True
        return False

    def heal(self, amount: int) -> int:
        """
        Restore HP up to max_hits. Returns the actual amount healed.
        """
        old: int = self.hits
        self.hits: int = min(self.max_hits, self.hits + amount)
        return self.hits - old

    def gain_xp(self, amount: int) -> bool:
        """
        Add XP. Handles level-up, stat boosts, and partial heal.
        Returns True on level-up.
        """
        self.xp += amount
        # Each level requires 30 more XP
        xp_needed: int = self.level * 30
        if self.xp >= xp_needed:
            self.xp -= xp_needed
            self.level += 1
            self.max_hits += 2  # Bonus by level

            heal_amount: int = max(3, self.max_hits // 3)
            self.hits: int = min(
                self.max_hits, self.hits + heal_amount
            )  # Heal by level-up
            return True
        return False

    def add_gold(self, amount: int):
        """Increase player gold."""
        self.gold += amount

    def add_armor(self, amount: int):
        """Increase armor value."""
        self.armor += amount

    def add_strength(self, amount: int):
        """Increase strength value."""
        self.strength += amount


@dataclass
class Enemy:
    """Dataclass representing a monster on the map."""

    x: int
    y: int
    sprite_type: str
    hits: int
    attack: int
    xp_reward: int


@dataclass
class Item:
    """Dataclass representing a pickup on the map."""

    x: int
    y: int
    type: str


class Room:
    """
    Represents a rectangular dungeon room with position, size,
    and center.
    """

    def __init__(self, x: int, y: int, w: int, h: int):
        """
        Initialize room with top-left coordinates and dimensions.
        """
        self.x, self.y, self.w, self.h = x, y, w, h
        self.cx, self.cy = x + w // 2, y + h // 2

    def overlaps(self, other: "Room", padding: int = 3) -> bool:
        """
        Check if this room overlaps another, respecting the padding gap.
        """
        return not (
            self.x + self.w + padding <= other.x
            or other.x + other.w + padding <= self.x
            or self.y + self.h + padding <= other.y
            or other.y + other.h + padding <= self.y
        )

    def door_position(self, other: "Room") -> tuple[int, int]:
        """
        Calculate a random door location on the wall facing `other`.
        """
        horizontal: bool = abs(self.cx - other.cx) >= abs(self.cy - other.cy)

        if horizontal:
            # left or right wall
            x = self.x if self.cx > other.cx else self.x + self.w - 1

            y1 = self.y + 1
            y2 = self.y + self.h - 2
            if y1 > y2:
                y1 = y2 = self.cy  # for small room
            y = random.randint(y1, y2)
        else:
            # upper or lower wall
            y = self.y if self.cy > other.cy else self.y + self.h - 1

            x1 = self.x + 1
            x2 = self.x + self.w - 2
            if x1 > x2:
                x1 = x2 = self.cx  # for small room
            x = random.randint(x1, x2)

        return x, y


class MapGenerator:
    """
    Generates a dungeon by placing prefabs and connecting them
    with corridors.
    """

    def __init__(
        self, width: int = 40, height: int = 25, prefabs: dict | None = None
    ):
        """
        Initialize generator with map size and optional
        prefab dictionary.
        """
        self.width: int = width
        self.height: int = height
        self.prefabs: dict = prefabs or {}
        self.rooms: list[Room] = []
        self.grid: list[list[str]] = [
            [" " for _ in range(width)] for _ in range(height)
        ]

    def generate(
        self, room_count: int = 5
    ) -> tuple[list[list[str]], list[Room]]:
        """
        Run generation: place rooms, carve corridors,
        return grid and room list.
        """
        attempts: int = room_count * 15
        for _ in range(attempts):
            if len(self.rooms) >= room_count:
                break
            name: str = random.choice(list(self.prefabs.keys()))
            prefab: list[list[str]] = self.prefabs[name]
            ph, pw = len(prefab), len(prefab[0])
            x: int = random.randint(2, self.width - pw - 2)
            y: int = random.randint(2, self.height - ph - 2)
            new_room = Room(x, y, pw, ph)

            if any(r.overlaps(new_room) for r in self.rooms):
                continue

            # "print" the prefab into the grid
            for dy, row in enumerate(prefab):
                for dx, char in enumerate(row):
                    self.grid[y + dy][x + dx] = char
            self.rooms.append(new_room)

        # Connect rooms sequentially with L-shaped corridors
        corridor_width = 1

        for i in range(len(self.rooms) - 1):
            r1, r2 = self.rooms[i], self.rooms[i + 1]

            d1x, d1y = r1.door_position(r2)
            d2x, d2y = r2.door_position(r1)

            # Place the doors only on upper walls of rooms
            self.grid[d1y][d1x] = TERRAIN_TILE["OPEN_DOOR"]
            self.grid[d2y][d2x] = TERRAIN_TILE["OPEN_DOOR"]

            # Build the corridor not through the doors,
            # but from the cage outside the room
            s1x, s1y = outside_point(r1, d1x, d1y)
            s2x, s2y = outside_point(r2, d2x, d2y)

            carve_corridor_wide(
                self.grid, s1x, s1y, s2x, s2y, width=corridor_width
            )

        return self.grid, self.rooms


# === Game State ===
class Entity:
    """Base class for map objects (player, monsters, items)."""

    def __init__(self, x: int, y: int, sprite_type: str):
        """Initialize entity with coordinates and sprite type."""
        self.x, self.y = x, y
        self.sprite_type: str = sprite_type


class GameState:
    """
    Manages the current game state:
    map, entities, player stats, and I/O.
    """

    def __init__(self, width: int = 40, height: int = 25):
        """
        Initialize game state with map dimensions and default values.
        """
        self.width: int = width
        self.height: int = height
        self.map_grid: list[list[str]] = []  # 2D for logic
        self.map_render: list[str] = []  # 1D for drawing
        self.entities: list[Entity] = []
        self.player_x, self.player_y = 0, 0
        self.rooms: list[Room] = []
        self.player_stats = PlayerStats()
        self.player = Entity(0, 0, "PLAYER")
        self.enemies: list[Enemy] = []
        self.items: list[Item] = []
        self.current_floor = 0
        self.save_file = Path("savegame.json")

    # It's not very well made, it might be worth redoing
    def save_game(self, filepath: str | Path = "savegame.json") -> bool:
        """
        Serialize current state to a JSON file.
        Returns True on success.
        """
        try:
            data = {
                "meta": {
                    "floor": self.current_floor,
                },
                "player": {
                    "x": self.player_x,
                    "y": self.player_y,
                    "stats": self.player_stats.__dict__,
                },
                "map": {
                    "width": self.width,
                    "height": self.height,
                    "grid": self.map_grid,
                },
                "enemies": [e.__dict__ for e in self.enemies],
                "items": [i.__dict__ for i in self.items],
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
                return True
        except Exception:
            return False

    def load_game(self, filepath: str | Path = "savegame.json") -> bool:
        """
        Deserialize state from a JSON file.
        Returns True on success.
        """
        try:
            if not Path(filepath).exists():
                return False

            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            # 1. Recovering the map and dimensions
            map_data = data["map"]
            self.width = map_data["width"]
            self.height = map_data["height"]
            self.map_grid = map_data["grid"]
            self.map_render = ["".join(row) for row in self.map_grid]

            # 2. Player position and stats
            pl = data["player"]
            self.player_x, self.player_y = pl["x"], pl["y"]
            self.player_stats = PlayerStats(**pl["stats"])

            # 3. Entities, enemies and objects
            self.player = Entity(self.player_x, self.player_y, "PLAYER")
            self.entities = [self.player]
            self.enemies = [Enemy(**e) for e in data["enemies"]]
            self.items = [Item(**i) for i in data["items"]]

            # 4. Metadata
            self.current_floor = data["meta"]["floor"]

            return True
        except Exception:
            return False

    def generate_level(self, prefabs: dict, room_count: int = 10):
        """
        Generate a new floor layout, place player/stairs, and
        populate enemies/items.

        Handles special logic for boss floors.
        """
        gen = MapGenerator(self.width, self.height, prefabs)
        self.map_grid, self.rooms = gen.generate(room_count=room_count)
        self.map_render: list[str] = ["".join(row) for row in self.map_grid]
        self.entities = []
        self.player = Entity(
            x=self.player_x,
            y=self.player_y,
            sprite_type="PLAYER",
        )
        self.entities.append(self.player)
        self.current_floor += 1

        if self.rooms:
            start: Room = self.rooms[0]  # first room (player)
            end: Room = self.rooms[-1]  # last room (stairs)

            self.player_x, self.player_y = start.cx, start.cy
            self.player.x, self.player.y = self.player_x, self.player_y

            self.map_grid[end.cy][end.cx] = TERRAIN_TILE["DOWN_STAIRS"]
            self.map_render: list[str] = [
                "".join(row) for row in self.map_grid
            ]

            if self.current_floor == 15:
                # Boss (dragon) floor
                self.enemies = []
                self.enemies.append(
                    Enemy(
                        end.cx,
                        end.cy,
                        "DRAGON",
                        hits=50,
                        attack=10,
                        xp_reward=150,
                    )
                )
            else:
                # Usual floor
                self.items = []
                self.enemies = []
                self.spawn_enemies(count=max(1, len(self.rooms) // 3))
                self.spawn_items(count=random.randint(3, 6))

    def spawn_items(self, count: int = 5) -> None:
        """Randomly place `count` items on valid walkable tiles."""
        # Accessed enemies from ENTITY_TILE
        item_types: list[str] = ["MONEY", "FOOD", "POTION", "ARMOR", "WEAPON"]

        occupied: set[tuple[int, int]] = {(e.x, e.y) for e in self.enemies} | {
            (self.player_x, self.player_y)
        }

        placed = 0
        attempts: int = count * 20
        while placed < count and attempts > 0:
            attempts -= 1
            room: Room = random.choice(self.rooms)
            x: int = random.randint(room.x + 1, room.x + room.w - 2)
            y: int = random.randint(room.y + 1, room.y + room.h - 2)

            if (x, y) in occupied or self.map_grid[y][x] != TERRAIN_TILE[
                "FLOOR"
            ]:
                continue

            new_item = Item(x=x, y=y, type=random.choice(item_types))
            self.items.append(new_item)
            occupied.add((x, y))
            placed += 1

    def item_at(self, x: int, y: int) -> Item | None:
        """Return the item at (x, y), or None if empty."""
        for item in self.items:
            if item.x == x and item.y == y:
                return item
        return None

    def spawn_enemies(self, count: int = 5) -> None:
        """Randomly place `count` enemies on valid walkable tiles."""
        variants: list[tuple[str, int, int, int]] = [
            # (type, hits, attack, xp_reward)
            ("SLIME", 6, 2, 2),
            ("KOBOLD", 8, 3, 4),
            ("ZOMBIE", 12, 4, 6),
        ]

        occupied: set[tuple[int, int]] = {(self.player_x, self.player_y)}

        attempts: int = count * 30
        placed = 0

        while placed < count and attempts > 0:
            attempts -= 1

            room: Room = random.choice(self.rooms)
            x: int = random.randint(room.x + 1, room.x + room.w - 2)
            y: int = random.randint(room.y + 1, room.y + room.h - 2)

            if (x, y) in occupied:
                continue
            if self.map_grid[y][x] != TERRAIN_TILE["FLOOR"]:
                continue

            kind, hp, attack, xp = random.choice(variants)
            self.enemies.append(
                Enemy(
                    x=x,
                    y=y,
                    sprite_type=kind,
                    hits=hp,
                    attack=attack,
                    xp_reward=xp,
                )
            )
            occupied.add((x, y))
            placed += 1

    def render(self) -> str:
        """
        Generate a formatted string representation of the map
        with overlaid entities.
        """

        # Copy the map
        display: list[list[str]] = [list(row) for row in self.map_render]

        # Draw enemies
        for enemy in self.enemies:
            if 0 <= enemy.y < len(display) and 0 <= enemy.x < len(display[0]):
                display[enemy.y][enemy.x] = ENTITY_TILE[enemy.sprite_type]

        # Draw items
        for item in self.items:
            if 0 <= item.y < len(display) and 0 <= item.x < len(display[0]):
                display[item.y][item.x] = ENTITY_TILE[item.type]

        # Draw player
        if 0 <= self.player_y < len(display) and 0 <= self.player_x < len(
            display[0]
        ):
            display[self.player_y][self.player_x] = ENTITY_TILE["PLAYER"]

        return "\n".join("".join(row).ljust(self.width) for row in display)

    def enemy_at(self, x: int, y: int) -> Enemy | None:
        """Return the enemy at (x, y), or None if empty."""
        for enemy in self.enemies:
            if enemy.x == x and enemy.y == y:
                return enemy
        return None

    def move_player(self, dx: int, dy: int) -> bool:
        """
        Attempt to move player by (dx, dy). Handles tile validation,
        combat,and item pickup.

        Returns True if an action was taken.
        """
        nx, ny = self.player_x + dx, self.player_y + dy

        # 1. Map borders
        if not (0 <= ny < self.height and 0 <= nx < self.width):
            return False

        target: str = self.map_grid[ny][nx]
        # 2. Checking: the tile should be on the "white list"
        if target not in WALKABLE_TERRAIN:
            return False  # Blocks: walls "#", emptiness " ", closed doors "+"

        enemy: Enemy | None = self.enemy_at(nx, ny)
        if enemy is not None:
            enemy.hits -= self.player_stats.strength
            if enemy.hits <= 0:
                self.enemies.remove(enemy)
                self.player_stats.gain_xp(enemy.xp_reward)
            else:
                is_dead = self.player_stats.take_damage(
                    max(0, enemy.attack - self.player_stats.armor)
                )
                if is_dead:
                    # Game over
                    pass
            return True

        self.player_x, self.player_y = nx, ny

        # Items logic
        item: Item | None = self.item_at(nx, ny)
        if item:
            if item.type == "MONEY":
                self.player_stats.add_gold(random.randint(1, 10))
            elif item.type == "POTION":
                self.player_stats.heal(4)
            elif item.type == "FOOD":
                self.player_stats.heal(2)
            elif item.type == "ARMOR":
                self.player_stats.add_armor(1)
            elif item.type == "WEAPON":
                self.player_stats.add_strength(1)

            # Delete item after pickup
            self.items.remove(item)

        # Updating the coordinates of the player entity
        self.entities[0].x, self.entities[0].y = nx, ny

        return True


# === The playing field widget ===
class GameScreen(Static):
    """Textual widget that renders the game map."""

    def __init__(self, game_state: GameState, **kwargs) -> None:
        """
        Initialize with a GameState reference and render the initial
        map.
        """
        super().__init__(**kwargs)
        self.game_state: GameState = game_state
        self.update(content=self.game_state.render())  # First render

    def refresh_map(self) -> None:
        """
        Redraw the map after game state changes.
        """

        self.update(content=self.game_state.render())


class MainMenu(Screen):
    """
    Main menu screen with New Game, Load, and Quit options.
    """

    def compose(self) -> ComposeResult:
        """Build menu layout."""
        yield Static("Rogue", id="title")
        yield Button("New Game", id="new_game")
        yield Button("Load Game", id="load_game")
        yield Button("Quit", id="quit")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks: start/load game or quit."""
        app = cast(RogueApp, self.app)

        if event.button.id == "new_game":
            app.game_state = GameState(width=80, height=30)
            app.game_state.generate_level(app.prefabs)
            app.push_screen(GamePlayScreen(app.game_state, app.prefabs))

        elif event.button.id == "load_game":
            if app.game_state.load_game():
                app.push_screen(GamePlayScreen(app.game_state, app.prefabs))
            else:
                app.notify("File of save is not found!", severity="error")

        elif event.button.id == "quit":
            self.app.exit(return_code=1)


class GamePlayScreen(Screen):
    """Main gameplay screen containing the map and stats panel."""

    def __init__(
        self, game_state: GameState, prefabs: dict[str, list[list[str]]]
    ):
        """Initialize with game state and prefabs."""
        super().__init__()
        self.game_state: GameState = game_state
        self.prefabs: dict[str, list[list[str]]] = prefabs

    def compose(self) -> ComposeResult:
        """Build gameplay layout."""
        yield GameScreen(self.game_state, id="game_display")
        yield StatsPanel(id="stats_panel")
        yield Header()
        yield Footer()


class StatsOverlay(Screen):
    """Overlay screen displaying detailed player statistics."""

    def __init__(self, stats: PlayerStats, floor: int):
        """Initialize with player stats and current floor."""
        super().__init__()
        self.stats: PlayerStats = stats
        self.floor: int = floor

    def compose(self) -> ComposeResult:
        """Build stats display UI."""
        xp_needed: int = self.stats.level * 30  # from gain_xp
        yield Static(
            content=f"📊 Stats • Floor {self.floor}\n\n"
            f"❤️  HP: {self.stats.hits} / {self.stats.max_hits}\n"
            f"⭐ XP: {self.stats.xp} / {xp_needed}\n"
            f"🎯 Level: {self.stats.level}\n"
            f"⚔️  Strength: {self.stats.strength}\n"
            f"🛡️  Armor: {self.stats.armor}\n"
            f"💰 Gold: {self.stats.gold}\n\n"
            f"[dim]ESC — close[/]",
            id="stats_overlay_content",
        )

    def on_key(self, event: Key) -> None:
        """Close overlay on ESC press."""
        if event.key == "escape":
            self.app.pop_screen()


# === Main app ===
class RogueApp(App):
    """Main Textual application for the rogue."""

    CSS_PATH = "style.tcss"
    SCREENS = {
        "main_menu": MainMenu,
    }
    BINDINGS = [
        ("v", "save_game", "Save Game"),
        ("escape", "back_to_menu", "Menu"),
        ("i", "show_stats", "Stats"),
    ]

    def __init__(self) -> None:
        """
        Initialize app, load prefabs, and set up initial game state.
        """
        super().__init__()
        self.prefabs: dict[str, list[list[str]]] = load_prefabs(
            folder="prefabs"
        )
        self.game_state = GameState(width=80, height=30)
        self.game_state.generate_level(self.prefabs)
        self._sync_stats()

    def compose(self) -> ComposeResult:
        """Build the main UI layout."""
        yield GameScreen(self.game_state)
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Push the main menu on startup."""
        self.push_screen(screen="main_menu")

    def action_save_game(self) -> None:
        """Save game state and notify user."""
        if self.game_state.save_game():
            self.notify("Game saved!", timeout=2)
        else:
            self.notify("Save failed!", timeout=3, severity="error")

    def action_back_to_menu(self) -> None:
        """Auto-save current progress and return to main menu."""
        self.game_state.save_game()
        self.pop_screen()

    def action_show_stats(self) -> None:
        """Open the detailed stats overlay screen."""
        self.push_screen(
            screen=StatsOverlay(
                stats=self.game_state.player_stats,
                floor=self.game_state.current_floor,
            )
        )

    def on_key(self, event: Key) -> None:
        """
        Process movement inputs, update game state, handle floor
        transitions, and check for game over conditions.
        """
        UP_KEYS: set[str] = {"up", "w", "k"}
        DOWN_KEYS: set[str] = {"down", "s", "j"}
        LEFT_KEYS: set[str] = {"left", "a", "h"}
        RIGHT_KEYS: set[str] = {"right", "d", "l"}

        moved = False

        if event.key in UP_KEYS:
            moved: bool = self.game_state.move_player(0, -1)
        elif event.key in DOWN_KEYS:
            moved: bool = self.game_state.move_player(0, 1)
        elif event.key in LEFT_KEYS:
            moved: bool = self.game_state.move_player(-1, 0)
        elif event.key in RIGHT_KEYS:
            moved: bool = self.game_state.move_player(1, 0)

        if not moved:
            return

        if (
            self.game_state.map_grid[self.game_state.player_y][
                self.game_state.player_x
            ]
            == TERRAIN_TILE["DOWN_STAIRS"]
        ):
            self.game_state.generate_level(self.prefabs, room_count=10)
            self.screen.query_one("#game_display", GameScreen).refresh_map()
            self._sync_stats()
            return

        if moved:
            self.screen.query_one("#game_display", GameScreen).refresh_map()
            self._sync_stats()

        if self.game_state.player_stats.hits <= 0:
            self.notify("GAME OVER!", severity="error", timeout=3)

            if self.game_state.save_file.exists():
                self.game_state.save_file.unlink()

            self.pop_screen()
            return

    def _sync_stats(self) -> None:
        """
        Update the stats panel with current player data.
        Silently ignores errors if the panel hasn't been drawn yet.
        """
        try:
            panel: StatsPanel = self.screen.query_one(
                "#stats_panel", StatsPanel
            )
            panel.sync(
                self.game_state.player_stats, self.game_state.current_floor
            )
        except Exception as e:  # noqa: F841
            pass  # It hasn't been drawn yet
            # self.notify(f"[DEBUG] _sync_stats failed: {e}")


if __name__ == "__main__":
    # Fast test of map
    st_test = 0
    if st_test == 1:
        print("=== TEST MAP ===")
        gs = GameState(40, 25)
        gs.generate_level(load_prefabs("prefabs"))
        print(gs.render())
        print("======================\n")
    else:
        app = RogueApp()
        app.run()
        sys.exit(app.return_code)
