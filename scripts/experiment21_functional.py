"""Run the retained Level 1 replay with live network/model connections blocked."""
import experiment21_run  # installs the offline socket guard
from level1_native_verification_replay import main

if __name__ == "__main__":
    raise SystemExit(main())
