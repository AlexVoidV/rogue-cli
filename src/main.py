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
    # NPCs
    "TRADER": "T",
    # Pickups
    "MONEY": "$",
    "FOOD": "%",
    "POTION": "!",
    "ARMOR": "=",
    "WEAPON": "^",
    "KEY": "~",
}

WALKABLE_TERRAIN: set[str] = {
    TERRAIN_TILE["FLOOR"],
    TERRAIN_TILE["OPEN_DOOR"],
    TERRAIN_TILE["UP_STAIRS"],
    TERRAIN_TILE["DOWN_STAIRS"],
    TERRAIN_TILE["TRAP"],
    TERRAIN_TILE["PORTAL"],
}


# TODO: GameEngine - moves, collision
# TODO: Stats - level, hits, str, gold, armor, exp, floor
# TODO: GameState - map, entities, inventory (primitive)
# TODO: Components - player, item, enemy
# TODO: Utils - FOV (fog of war), pathfinding for enemies
# TODO: Actions - e - use, f - attack,
# y/n - yes/no, i - stats, esc - menu
# TODO: Save/Load


# === Map generator ===
def load_prefabs(folder: str) -> dict[str, list[list[str]]]:
    """
    Load room prefabs from `.txt` files in a folder.

    Each file becomes a 2D list of characters (grid).
    Filename without extension is used as the prefab name.

    Args:
        folder (str): Path to folder containing `.txt` prefab files

    Returns:
        dict[str, list[list[str]]]: Dictionary mapping prefab
        names to 2D grids.
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
    Carve an L-shaped corridor between two points.

    Path: horizontal first (x1 → x2 at y1),
    then vertical (y1 → y2 at x2).

    Corridor width applies symmetrically around the center line.

    Args:
        grid (list[list[str]]): 2D terrain grid to modify in-place

        x1 (int), y1 (int): Start coordinates (e.g., center of room A)

        x2 (int), y2 (int): End coordinates (e.g., center of room B)

        width (int, optional): Corridor thickness in
        tiles (1 or 2 recommended). Defaults to 3.
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
    if door_x == room.x:  # left wall
        return door_x - 1, door_y
    if door_x == room.x + room.w - 1:  # right wall
        return door_x + 1, door_y
    if door_y == room.y:  # upper wall
        return door_x, door_y - 1
    # lower wall
    return door_x, door_y + 1


class Room:
    """
    Represents a rectangular room placed on the map.

    Stores position, size, and pre-calculated center point
    for easy corridor connection.
    """

    def __init__(self, x: int, y: int, w: int, h: int):
        """
        Args:
            x (int), y (int): Top-left corner coordinates

            w (int), h (int): Room dimensions (width, height)
        """
        self.x, self.y, self.w, self.h = x, y, w, h
        self.cx, self.cy = x + w // 2, y + h // 2

    def overlaps(self, other: "Room", padding: int = 3) -> bool:
        """
        Check if this room overlaps another (with optional padding).

        Uses AABB collision detection. Padding ensures space
        between rooms for corridors.

        Args:
            other (Room): The other Room object to check collision
            against.

            padding (int, optional): Minimum gap (in tiles) to maintain
                between the edges of the two rooms. Defaults to 3.

        Returns:
            bool: `True` if the rooms overlap
            (including the padding zone), meaning they cannot both
            be placed on the map. `False` if the rooms are
            sufficiently separated and can coexist.
        """
        return not (
            self.x + self.w + padding <= other.x
            or other.x + other.w + padding <= self.x
            or self.y + self.h + padding <= other.y
            or other.y + other.h + padding <= self.y
        )

    def door_position(self, other: "Room") -> tuple[int, int]:
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
    Generates a dungeon by placing prefabs and connecting them.

    Algorithm:
    1. Place N rooms at random non-overlapping positions
    2. Connect rooms sequentially with L-shaped corridors
    3. Return final grid and list of placed rooms
    """

    def __init__(
        self, width: int = 40, height: int = 25, prefabs: dict | None = None
    ):
        """
        Args:
            width (int, optional): Width of the generated map in tiles
            Defaults to 40.

            height (int, optional): Height of the generated map in tiles
            Defaults to 25.

            prefabs (dict | None, optional): Dictionary of pre-made room
            templates.
            Defaults to None.
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
        """Run the dungeon generation algorithm.

        Args:
            room_count (int, optional): Target number of rooms to place.
            Defaults to 5.

        Returns:
            tuple[list[list[str]], list[Room]]:
            (final 2D grid, list of placed Room objects)
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
    """
    Base class for anything that exists on the map
    (player, monsters, items).

    Stores position and sprite type; rendering/collision
    logic is handled by GameState.
    """

    def __init__(self, x: int, y: int, sprite_type: str):
        """
        Args:
            x (int): X-coordinate (column) where the entity is placed

            y (int): Y-coordinate (row) where the entity is placed

            sprite_type (str): Key name from the `ENTITY_TILE`
            dictionary that determines which character represents this
            entity
        """
        self.x, self.y = x, y
        self.sprite_type: str = sprite_type


class GameState:
    """Initialize the game state with map dimensions"""

    def __init__(self, width: int = 40, height: int = 25):
        """
        Args:
            width (int, optional): Map width in tiles. Defaults to 40.
            height (int, optional): Map height in tiles. Defaults to 25.
        """
        self.width: int = width
        self.height: int = height
        self.map_grid: list[list[str]] = []  # 2D for logic
        self.map_render: list[str] = []  # 1D for drawing
        self.entities: list[Entity] = []
        self.player_x, self.player_y = 0, 0
        self.rooms: list[Room] = []

    def generate_level(self, prefabs: dict):
        """Generate a new dungeon level and place player/stairs.

        Steps:
        1. Create MapGenerator and run generate()
        2. Place player in center of first room
        3. Place down-stairs in center of last room
        4. Update map_render for display

        Args:
            prefabs (dict): Dictionary of prefab templates, as returned
            by `load_prefabs()`.
        """
        gen = MapGenerator(self.width, self.height, prefabs)
        self.map_grid, self.rooms = gen.generate(room_count=5)
        self.map_render: list[str] = ["".join(row) for row in self.map_grid]

        if self.rooms:
            # The player in first room
            start: Room = self.rooms[0]
            self.player_x, self.player_y = start.cx, start.cy
            self.entities = []
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
        """Compose final display: terrain + entities overlay.

        Returns:
            str: Multi-line string with .ljust() padding
            to preserve alignment in Textual.
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

        # 1. Map borders
        if not (0 <= ny < self.height and 0 <= nx < self.width):
            return False

        # 2. Checking: the tile should be on the "white list"
        if self.map_grid[ny][nx] not in WALKABLE_TERRAIN:
            return False  # Blocks: walls "#", emptiness " ", closed doors "+"

        self.player_x, self.player_y = nx, ny
        # Updating the coordinates of the player entity
        self.entities[0].x, self.entities[0].y = nx, ny
        return True


# === The playing field widget ===
class GameScreen(Static):
    """The widget that draws the map"""

    def __init__(self, game_state: GameState) -> None:
        """
        Args:
            game_state (GameState): The GameState instance that holds
            the current map, entities, and player position
        """
        super().__init__()
        self.game_state: GameState = game_state
        self.update(content=self.game_state.render())  # First render

    def refresh_map(self) -> None:
        """Just redraws the map after the player has moved

        To call after a state change"""

        self.update(content=self.game_state.render())


# === Main app ===
class RogueApp(App):
    """Main Application"""

    CSS_PATH = "style.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.prefabs: dict[str, list[list[str]]] = load_prefabs(
            folder="prefabs"
        )
        self.game_state = GameState(width=40, height=25)
        self.game_state.generate_level(self.prefabs)

    def compose(self) -> ComposeResult:
        """Build the UI by yielding widgets in display order.

        Yields:
            GameScreen: The main viewport showing the dungeon map.

            Header: Textual's built-in header widget (shows app title).

            Footer: Textual's built-in footer widget
            (shows key bindings).
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
