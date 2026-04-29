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
    """The class (drawing) of the game state"""

    def __init__(self) -> None:
        self.map: list[str] = [
            "########",  # y=0
            "#......#",
            "#.##...#",
            "#..@...#",  # y=3
            "#......#",
            "########",  # y=5
        ]
        self.player_x, self.player_y = 3, 3  # Start pos of '@' (player)

    def render(self) -> str:
        """Takes a list of strings and connects them via a `\\n`

        Returns:
            str: The string to render
        """

        return "\n".join(self.map)

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
    """The widget that draws the map

    Args:
        Static (Static): ready-made Textual widget for displaying static
        text
    """

    def __init__(self, game_state: GameState) -> None:
        super().__init__()
        self.game_state: GameState = game_state
        self.update(self.game_state.render())  # First render

    def refresh_map(self) -> None:
        """Just redraws the map after the player has moved

        To call after a state change"""

        self.update(self.game_state.render())


# === Main app ===
class RogueApp(App):
    """Main Application

    Args:
        App (App): the main Textual class
    """

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
