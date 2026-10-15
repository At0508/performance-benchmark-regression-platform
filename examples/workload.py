"""Deterministic pure-Python workload to demonstrate suite execution."""

import argparse


def checksum(size: int, repeats: int, seed: int) -> int:
    values = [((index * 17 + seed) % 101) - 50 for index in range(size)]
    total = 0
    for _ in range(repeats):
        for row in range(size):
            for column in range(size):
                total += values[row] * values[column]
    return total


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=48)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    if min(args.size, args.repeats) <= 0:
        parser.error("size and repeats must be positive")
    print(checksum(args.size, args.repeats, args.seed))


if __name__ == "__main__":
    main()
