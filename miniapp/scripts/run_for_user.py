import argparse
from miniapp.runner import run_for_user


def main():
    ap = argparse.ArgumentParser(description="Run parsing for a single user now")
    ap.add_argument("user_id")
    args = ap.parse_args()
    run_for_user(str(args.user_id), ignore_window=True)
    print("Triggered run_for_user")


if __name__ == "__main__":
    main()
