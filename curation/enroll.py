import argparse
from pathlib import Path
from .engine import Engine


def main():
    parser = argparse.ArgumentParser(description="Enroll a local agent; token is printed once.")
    parser.add_argument("agent")
    parser.add_argument("--kb", default="demo")
    parser.add_argument("--db", default="data/curation.sqlite3")
    parser.add_argument("--role", choices=["reviewer", "contributor", "admin"], default="reviewer")
    parser.add_argument("--model", default="simulated")
    args = parser.parse_args()
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    print(Engine(args.db).enroll(args.kb, args.agent, args.role, args.model))


if __name__ == "__main__":
    main()
