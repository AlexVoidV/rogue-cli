from textual.app import App, ComposeResult
from textual.widgets import Static, Footer, Header
from textual.events import Key


# === Configuration ===
TILE: dict[str, str] = {
    "WALL": "#",
    "FLOOR": ".",
    "PLAYER": "@",
}


# === Game State ===
class GameState:
    def __init__(self) -> None:
        self.map: list[str] = [
            "########",
            "#......#",
            "#.##...#",
            "#..@...#",
            "#......#",
            "########",
        ]
        self.player_x, self.player_y = 3, 3  # Start pos of '@' (player)

    def render(self) -> str:
        """Returns the string to render"""
        return "\n".join(self.map)

    def move_player(self, dx: int, dy: int) -> bool:
        """Tries to move the player. Returns success (True)"""
        new_x, new_y = self.player_x + dx, self.player_y + dy
        # Checking borders and walls
        if (
            0 <= new_y < len(self.map)
            and 0 <= new_x < len(self.map[new_y])
            and self.map[new_y][new_x] != TILE["WALL"]
        ):
            # Erasing the player in the old position
            row: str = self.map[self.player_y]
            self.map[self.player_y] = (
                row[: self.player_x] + TILE["FLOOR"] + row[self.player_x + 1 :]
            )

            # Putting the player on a new pos
            row: str = self.map[new_y]
            self.map[new_y] = row[:new_x] + TILE["PLAYER"] + row[new_x + 1 :]

            # Updating the coordinates
            self.player_x, self.player_y = new_x, new_y
            return True
        return False


# === The playing field widget ===
class GameScreen(Static):
    """The widget that draws the map"""

    def __init__(self, game_state: GameState) -> None:
        super().__init__()
        self.game_state: GameState = game_state
        self.update(self.game_state.render())  # First render

    def refresh_map(self) -> None:
        """To call after a state change"""
        self.update(self.game_state.render())


# === Main app ===
class RogueApp(App):
    # A temporary solution
    CSS = """
    GameScreen {
        width: 100%;
        height: 100%;
        background: black;
        color: green;
        text-style: bold;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.game_state = GameState()

    def compose(self) -> ComposeResult:
        yield GameScreen(self.game_state)
        yield Header()
        yield Footer()

    def on_key(self, event: Key) -> None:
        """Input Handler"""
        moved = False
        if event.key == "up" or event.key == "k":
            moved: bool = self.game_state.move_player(0, -1)
        elif event.key == "down" or event.key == "j":
            moved: bool = self.game_state.move_player(0, 1)
        elif event.key == "left" or event.key == "h":
            moved: bool = self.game_state.move_player(-1, 0)
        elif event.key == "right" or event.key == "l":
            moved: bool = self.game_state.move_player(1, 0)

        if moved:
            self.query_one(GameScreen).refresh_map()


if __name__ == "__main__":
    app = RogueApp()
    app.run()
