from pathlib import Path


def main():
    folder: Path = Path(__file__).parent  # Path search for 'prefabs/'

    files: list[Path] = sorted(folder.glob("*.txt"))
    if not files:
        print(f"📭 There are no '.txt' files in the {folder}")
        return

    print(f"📐 Prefab sizes in '{folder}/':\n")
    header = f"{'File':<25} | {'Height (Y)':<12} | {'Width (X)':<12}"
    print(header)
    print("-" * len(header))

    for file in files:
        with open(file, "r", encoding="utf-8") as f:
            # Removing line breaks and empty lines
            lines: list[str] = [line.rstrip() for line in f if line.strip()]

        if not lines:
            h, w = 0, 0
        else:
            h: int = len(lines)
            w_values: set[int] = {len(line) for line in lines}
            # If the line lengths are different, we output a range and
            # a warning
            if len(w_values) == 1:
                w = str(w_values.pop())
            else:
                w = f"{min(w_values)}-{max(w_values)} ⚠️"

        print(f"{file.name:<25} | {h:<12} | {w:<12}")

    print("\n✅ Verification completed!")


if __name__ == "__main__":
    main()
