from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Static, Footer, Header
from textual.events import Key
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
    "UP_STAIRS": "<",
    "DOWN_STAIRS": ">",
    # Special
    "TRAP": "?",
    "PORTAL": "X",
}

ENTITY_TILE: dict[str, str] = {
    # Player
    "PLAYER": "@",
    # Monsters
    "SLIME": "S",
    "KOBOLD": "K",
    "ZOMBIE": "Z",
    "MIMIC": "M",
    "DRAGON": "D",
    # Pickups
    "MONEY": "$",
    "FOOD": "%",
    "POTION": "!",
    "ARMOR": "=",
    "WEAPON": "^",
}


# TODO: GameEngine - moves, collision
# TODO: Stats - level, hits, str, gold, armor, exp, floor
# TODO: GameState - map, entities, inventory (primitive)
# TODO: Components - player, item, enemy
# TODO: Utils - FOV (fog of war), pathfinding for enemies
# TODO: Movements - e - use, f - attack,
# y/n - yes/no, i - stats, esc - menu


# === Map generator ===
def load_prefabs(folder: str) -> dict[str, list[list[str]]]:
    cache: dict[str, list[list[str]]] = {}
    for p in Path(folder).glob(pattern="*.txt"):
        with open(file=p, encoding="utf-8") as f:
            cache[p.stem] = [list(line.rstrip()) for line in f if line.strip()]
    return cache


def carve_corridor_wide(
    grid: list[list[str]], x1: int, y1: int, x2: int, y2: int, width: int = 3
):
    h, w = len(grid), len(grid[0])
    half: int = width // 2

    # Horizontal segment
    x_start, x_end = min(x1, x2), max(x1, x2)
    for x in range(x_start, x_end + 1):
        for dy in range(-half, half + 1):
            ny: int = y1 + dy
            if 0 <= ny < h:
                grid[ny][x] = TERRAIN_TILE["FLOOR"]

    # Vertical segment
    y_start, y_end = min(y1, y2), max(y1, y2)
    for y in range(y_start, y_end + 1):
        for dx in range(-half, half + 1):
            nx: int = x2 + dx
            if 0 <= nx < w:
                grid[y][nx] = TERRAIN_TILE["FLOOR"]


class Room:
    def __init__(self, x: int, y: int, w: int, h: int):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.cx, self.cy = x + w // 2, y + h // 2

    def overlaps(self, other: "Room", padding: int = 3) -> bool:
        return not (
            self.x + self.w + padding <= other.x
            or other.x + other.w + padding <= self.x
            or self.y + self.h + padding <= other.y
            or other.y + other.h + padding <= self.y
        )


class MapGenerator:
    def __init__(
        self, width: int = 40, height: int = 25, prefabs: dict | None = None
    ):
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

        # Connect the rooms with wide corridors
        for i in range(len(self.rooms) - 1):
            r1, r2 = self.rooms[i], self.rooms[i + 1]
            carve_corridor_wide(self.grid, r1.cx, r1.cy, r2.cx, r2.cy, width=3)

        return self.grid, self.rooms


# === Game State ===
class Entity:
    def __init__(self, x: int, y: int, sprite_type: str):
        self.x, self.y = x, y
        self.sprite_type: str = sprite_type


class GameState:
    """The class (drawing) of the game state"""

    def __init__(self, width: int = 40, height: int = 25):
        self.width: int = width
        self.height: int = height
        self.map_grid: list[list[str]] = []  # 2D for logic
        self.map_render: list[str] = []  # 1D for drawing
        self.entities: list[Entity] = []
        self.player_x, self.player_y = 0, 0
        self.rooms: list[Room] = []

    def generate_level(self, prefabs: dict):
        gen = MapGenerator(self.width, self.height, prefabs)
        self.map_grid, self.rooms = gen.generate(room_count=5)
        self.map_render: list[str] = ["".join(row) for row in self.map_grid]

        if self.rooms:
            # The player in first room
            start: Room = self.rooms[0]
            self.player_x, self.player_y = start.cx, start.cy
            self.entities.append(
                Entity(x=self.player_x, y=self.player_y, sprite_type="PLAYER")
            )

            # The stairs in the last room
            end: Room = self.rooms[-1]
            self.map_grid[end.cy][end.cx] = TERRAIN_TILE["DOWN_STAIRS"]
            self.map_render[end.cy] = (
                self.map_render[end.cy][: end.cx]
                + TERRAIN_TILE["DOWN_STAIRS"]
                + self.map_render[end.cy][end.cx + 1 :]
            )

    def render(self) -> str:
        """Takes a list of strings and connects them via a `\\n`

        Returns:
            str: The string to render
        """

        # Copy the map
        display: list[list[str]] = [list(row) for row in self.map_render]
        # Draw entities
        for ent in self.entities:
            if 0 <= ent.y < len(display) and 0 <= ent.x < len(display[0]):
                display[ent.y][ent.x] = ENTITY_TILE[ent.sprite_type]

        return "\n".join("".join(row).ljust(self.width) for row in display)

    def move_player(self, dx: int, dy: int) -> bool:
        """Tries to move the player

        Args:
            dx (int): X-direction change (horizontal): `-1` = left,
            `+1` = right

            dy (int): Y-direction change (vertical): `-1` = up,
            `+1` = down

        Returns:
            bool: `True` (Success) or `False` (Fail)
        """

        nx, ny = self.player_x + dx, self.player_y + dy
        if (
            0 <= ny < self.height
            and 0 <= nx < self.width
            and self.map_grid[ny][nx] != TERRAIN_TILE["WALL"]
        ):
            self.player_x, self.player_y = nx, ny
            # Updating the coordinates of the player entity
            self.entities[0].x, self.entities[0].y = nx, ny
            return True
        return False


# === The playing field widget ===
class GameScreen(Static):
    """The widget that draws the map

    Args:
        Static (Static): ready-made Textual widget for displaying static
        text
    """

    def __init__(self, game_state: GameState) -> None:
        super().__init__()
        self.game_state: GameState = game_state
        self.update(content=self.game_state.render())  # First render

    def refresh_map(self) -> None:
        """Just redraws the map after the player has moved

        To call after a state change"""

        self.update(content=self.game_state.render())


# === Main app ===
class RogueApp(App):
    """Main Application

    Args:
        App (App): the main Textual class
    """

    CSS_PATH = "style.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.prefabs: dict[str, list[list[str]]] = load_prefabs(
            folder="prefabs"
        )
        self.game_state = GameState(width=40, height=25)
        self.game_state.generate_level(self.prefabs)

    def compose(self) -> ComposeResult:
        """A special Textual method that shows widgets

        Returns:
            ComposeResult: a widget that builds an interface using other
            widgets

        Yields:
            Iterator[ComposeResult]: returns the container widget,
            saving the state of all variables
        """

        yield GameScreen(self.game_state)
        yield Header()
        yield Footer()

    def on_key(self, event: Key) -> None:
        """Reaction to the keys (Input Handler)

        Args:
            event (Key): an object with information about the key
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

        if moved:
            self.query_one(selector=GameScreen).refresh_map()


if __name__ == "__main__":
    app = RogueApp()
    app.run()
