"""Compatibility entry point for the single supported, privacy-preserving workflow."""
from privacy import canonical_goal


def run_message(message, **kwargs):
    canonical_goal(message)  # raw message never reaches the model or a log
    from runner import discover
    return discover(**kwargs)


if __name__ == "__main__":
    from demo import main
    main()
