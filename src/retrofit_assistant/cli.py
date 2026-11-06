import argparse


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m retrofit_assistant",
        description="Advisory-only operator assistance for the RETROFIT AI challenge.",
    )
    parser.parse_args(argv)
    parser.print_help()
    return 0
